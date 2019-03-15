#!/usr/bin/env python3

import click
import copy
import sys
import sh
import os
import re
import glob
import pprint
import string
import subprocess
#from io import StringIO
import io
from contextlib import redirect_stdout


from random import shuffle
from youtube_dl.extractor import YoutubeChannelIE
from youtube_dl.compat import compat_expanduser
from youtube_dl.extractor import gen_extractors
from youtube_dl import YoutubeDL
from kcl.printops import ceprint
from kcl.printops import eprint
from kcl.fileops import points_to_data

import sre_constants

extractors = gen_extractors()
QUEUE_CMD = ['/home/cfg/redis/rpush', 'mpv']
downloaded_video_list = []

VIDEO_CMD = ['/usr/bin/xterm',
             '-e',
             '/usr/bin/mpv',
             '--cache-pause',
             '--hwdec=vdpau',
             '--cache-initial=75000',
             '--cache-default=275000',
             '--pause']

FILE_TEMPLATE = '%(extractor)s' + '/' + '%(uploader)s' + '/' + "%(uploader_id)s__%(upload_date)s__%(title)s__%(id)s.%(ext)s"

MAX_TRIES = 3


## https://stackoverflow.com/questions/16571150/how-to-capture-stdout-output-from-a-python-function-call
#class Capturing(list):
#    def __enter__(self):
#        self._stdout = sys.stdout
#        sys.stdout = self._stringio = StringIO()
#        return self
#    def __exit__(self, *args):
#        self.extend(self._stringio.getvalue().splitlines())
#        del self._stringio    # free up some memory
#        sys.stdout = self._stdout


def is_non_zero_file(fpath):
    if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
        return True
    return False


class NoIDException(ValueError):
    pass


class NoMatchException(ValueError):
    pass


def extract_id_from_url(url):
    #ceprint("url:", url)
    #ceprint("extractors:", extractors)
    for e in extractors:
        #try:
        #ceprint(e)
        try:
            regex = e._VALID_URL
        except AttributeError:
            continue

        try:
            urlid = re.match(regex, url, re.VERBOSE).groups()[-1]
        except AttributeError:
            continue
        except sre_constants.error:
            continue
        extractor = e.IE_NAME
        ceprint("using extractor:", e.IE_NAME) #youtube:user
        if e.IE_NAME == 'youtube':
            try:
                if len(urlid) != 11:
                    return False
            except TypeError:
                return False

        return urlid, extractor
        #except re.error:
        #    pass
        #except AttributeError:
        #    pass
        #except IndexError:
        #    pass
    raise NoIDException


def download_id_for_url(url):
    ceprint(url)
    ydl_ops = {
        'simulate': True,
        'skip_download': True
    }
    with YoutubeDL(ydl_ops) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
        try:
            if info['id']:
                return info['id']
        except KeyError:
            return False


def get_filename_for_url(url, ydl_ops):
    ceprint(url)
    ydl_ops['forcefilename'] = True
    ydl_ops['skip_download'] = True
    ydl_ops['quiet'] = True
    f = io.StringIO()

    with redirect_stdout(f):
        with YoutubeDL(ydl_ops) as ydl:
            ydl.download([url])
        out = f.getvalue()

    assert out
    ceprint("out:", out)
    return out


def get_clipboard():
    clipboard_text = \
        subprocess.Popen(["xclip", "-o"], stdout=subprocess.PIPE).stdout.read()
    clipboard_text_utf8 = clipboard_text.decode("utf-8")
    ceprint("clipboard_text_utf8:", clipboard_text_utf8)
    return clipboard_text_utf8


def get_clipboard_urls():
    clipboard_text = get_clipboard()
    urls = extract_urls_from_text(clipboard_text)
    return urls


def extract_urls_from_text(intext):
    text = intext.split("\n")
    clean_text = filter(None, text)
    extracted_url_list = []
    for line in clean_text:
        for word in line.split(' '):
            urls = re.findall('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+#]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', word)
            if len(urls) == 0:
                constructed_url = construct_youtube_url_from_id(ytid=word)
                if constructed_url:
                    urls.append(constructed_url)
            for url in urls:
                extracted_url_list.append(url)

    url_set = set(extracted_url_list)
    return list(url_set)


def check_lsof_for_duplicate_process(video_id):
    lsof_check = ""
    lsof_check = sh.grep(sh.lsof(), video_id)

    if len(lsof_check) > 0:
        ceprint("lsof_check:", lsof_check)
        ceprint("Found", video_id, "in lsof output, skipping.")
        return True
    return False

def get_playlist_for_channel(url):
    ydl = YoutubeDL()
    ie = YoutubeChannelIE(ydl)
    info = ie.extract(url)
    return info['url']

def check_if_video_exists_by_video_id(video_id):
    pre_matches = glob.glob('./*' + video_id + '*')
    matches = []
    ceprint("pre_matches:", pre_matches)
    for match in pre_matches:
        match = os.path.realpath(match)
        if match.endswith('.description'):
            continue
        if match.endswith('.json'):
            continue
        if match.endswith('.part'):
            continue
        match_ending = match.split(video_id)[-1]
        ceprint("match_ending:", match_ending)
        matches.append(match)
    if matches:
        ceprint("matches:", matches)
        return matches[0]
    raise NoMatchException

def generate_download_options(cache_dir=False, ignore_download_archive=True, play=False, verbose=False, archive_file=False):
    play_command = ' '.join(VIDEO_CMD) + ' {}'
    queue_command = ' '.join(QUEUE_CMD) + ' {}'

    if play:
        exec_cmd = queue_command + ' ; ' + play_command + ' & '
    else:
        exec_cmd = queue_command

    #ceprint("exec_cmd:", exec_cmd)
    ydl_ops = {
        'socket_timeout': 60,
        'ignoreerrors': True,
        'continuedl': True,
        'retries': 25,
        'noplaylist': False,
        'playlistrandom': True,
        'nopart': True,
        'writedescription': True,
        'writeannotations': True,
        'writeinfojson': True,
        'writesubtitles': True,
        'allsubtitles': True,
        "source_address": "0.0.0.0",
        'progress_with_newline': False,
        'consoletitle': True,
        'call_home': False,
        'postprocessors': [{
            'key': 'ExecAfterDownload',
            'exec_cmd': exec_cmd,
        }],
    }

    if cache_dir:
        ydl_ops['outtmpl'] = cache_dir + '/sources/' + FILE_TEMPLATE
    else:
        ydl_ops['outtmpl'] = FILE_TEMPLATE

    if verbose:
        ydl_ops['verbose'] = True

    if not ignore_download_archive:
        ydl_ops['download_archive'] = archive_file

    return ydl_ops


def get_playlist_links(url, ydl_ops):
    links = []

    ydl_ops['dumpjson'] = True
    ydl_ops['extract_flat'] = True

    tries = 0
    while not links:
        tries += 1
        try:
            with YoutubeDL(ydl_ops) as ydl:
                json_info = ydl.extract_info(url, download=False)
            pprint.pprint(json_info)
            for item in json_info['entries']:
                links.append('https://www.youtube.com/watch?v=' + item['url'])
        except Exception as e:
            print(e)
            if tries > MAX_TRIES:
                raise e

    return links


def download_url(url, ydl_ops):
    assert url
    with YoutubeDL(ydl_ops) as ydl:
        ydl.download([url])


def construct_youtube_url_from_id(ytid):
    if len(ytid) == 11:
        allowed = set(string.ascii_lowercase + string.ascii_uppercase + string.digits + '_' + '-')
        if set(ytid) <= allowed:
            ceprint("found bare youtube id:", ytid)
            url = 'https://www.youtube.com/watch?v=' + ytid
            return url
    return False


@click.command()
@click.argument('urls', nargs=-1)
@click.option('--id-from-url', is_flag=True)
@click.option('--ignore-download-archive', is_flag=True)
@click.option('--play', is_flag=True)
@click.option('--verbose', is_flag=True)
@click.option('--destdir', is_flag=False, required=False, default='~/_youtube')
@click.option('--archive-file', is_flag=False, required=False, default='~/.youtube_dl.cache')
def youtube_dl_wrapper(urls, id_from_url, ignore_download_archive, play, verbose, destdir, archive_file):
    if not urls:
        ceprint("no args, checking clipboard for urls")
        urls = get_clipboard_urls()

    urls = list(urls)
    shuffle(urls)
    cache_folder = compat_expanduser(destdir)
    try:
        os.chdir(cache_folder)
    except FileNotFoundError:
        print("Unable to os.chdir() to", cache_folder, "Press enter to retry.")
        input('pause')
        os.chdir(cache_folder)

    ydl_ops = generate_download_options(cache_dir=cache_folder, ignore_download_archive=ignore_download_archive, play=play, verbose=verbose, archive_file=archive_file)
    for index, url in enumerate(urls):
        eprint('(outer) (' + str(index+1), "of", str(len(urls)) + '):', url)
        if id_from_url:
            print(download_id_for_url(url))
            continue

        url_id, extractor = extract_id_from_url(url)
        ceprint("extractor:", extractor)
        ceprint("str(extractor):", str(extractor))
        ceprint("type(extractor):", type(extractor))
        if extractor in ['youtube:channel']:
            url = get_playlist_for_channel(url)
            url_id, extractor = extract_id_from_url(url)  # re-get now that user is converted to channel playlist

        if extractor in ['youtube:playlist']:
            playlist_links = get_playlist_links(url=url, ydl_ops=copy.copy(ydl_ops))
            for plindex, plurl in enumerate(playlist_links):
                eprint('(' + str(plindex+1), "of", str(len(playlist_links)) + '):', url)
                output_file = get_filename_for_url(url=plurl, ydl_ops=copy.copy(ydl_ops))
                assert output_file
                ceprint("output_file:", output_file)
                while not points_to_data(output_file):
                    download_url(url=plurl, ydl_ops=copy.copy(ydl_ops))
        else:
            download_url(url=url, ydl_ops=ydl_ops)

        print(" ")
