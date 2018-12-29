#!/usr/bin/env python3

import click
import sh
import os
import re
import glob
import string
import subprocess
import youtube_dl

from youtube_dl.compat import compat_expanduser
from youtube_dl.extractor import gen_extractors
from kcl.printops import ceprint

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


def is_non_zero_file(fpath):
    if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
        return True
    return False


class NoIDException(ValueError):
    pass


class NoMatchException(ValueError):
    pass


def extract_id_from_url(url):
    for e in extractors:
        try:
            regex = e._VALID_URL
            urlid = re.match(regex, url, re.VERBOSE).groups()[-1]
            extractor = e.IE_NAME
#            print("using extractor:", e.IE_NAME) #youtube:user
            if 'youtube' in e.IE_NAME:
                try:
                    if len(urlid) != 11:
                        return False
                except TypeError:
                    return False
            return urlid, extractor
        except re.error:
            pass
        except AttributeError:
            pass
        except IndexError:
            pass
    raise NoIDException


def download_id_for_url(url):
    print("download_id_for_url():", url)
    ydl_opts = {
        'simulate': True,
        'skip_download': True
    }
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
        try:
            if info['id']:
                return info['id']
        except KeyError:
            return False


def get_clipboard():
    clipboard_text = \
        subprocess.Popen(["xclip", "-o"], stdout=subprocess.PIPE).stdout.read()
    clipboard_text_utf8 = clipboard_text.decode("utf-8")
    print("clipboard_text_utf8:", clipboard_text_utf8)
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
        print("lsof_check:", lsof_check)
        print("Found", video_id, "in lsof output, skipping.")
        return True
    return False


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
        print("match_ending:", match_ending)
        matches.append(match)
    if matches:
        ceprint("matches:", matches)
        return matches[0]
    raise NoMatchException


def download_url(url, cache_dir, ignore_download_archive, play, verbose, archive_file):
    assert url
    play_command = ' '.join(VIDEO_CMD) + ' {}'
    queue_command = ' '.join(QUEUE_CMD) + ' {}'

    if play:
        exec_cmd = queue_command + ' ; ' + play_command + ' & '
    else:
        exec_cmd = queue_command

    ceprint("exec_cmd:", exec_cmd)
    ydl_opts = {
        'forcefilename': True,
        'socket_timeout': 30,
        'outtmpl': cache_dir + '/sources/' + '%(extractor)s' + '/' + '%(uploader)s' + '/' + "%(uploader_id)s__%(upload_date)s__%(title)s__%(id)s.%(ext)s",
        'ignoreerrors': True,
        'continue': True,
        'retries': 20,
        'playlist': False,
        'nopart': True,
        'fragment_retries': 10,
        'writedescription': True,
        'playlistrandom': True,
        'writeinfojson': True,
        'allsubtitles': True,
        "source_address": "0.0.0.0",
        'progress_with_newline': False,
        'postprocessors': [{
            'key': 'ExecAfterDownload',
            'exec_cmd': exec_cmd,
        }],
    }

    if verbose:
        ydl_opts['verbose'] = True

    if not ignore_download_archive:
        ydl_opts['download_archive'] = archive_file
    print("url:", url)
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
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

    cache_folder = compat_expanduser(destdir)
    try:
        os.chdir(cache_folder)
    except FileNotFoundError:
        print("Unable to os.chdir() to", cache_folder, "Press enter to retry.")
        input('pause')
        os.chdir(cache_folder)

    for url in urls:
        print(url)
        if id_from_url:
            print(download_id_for_url(url))
            continue
        download_url(url=url, cache_dir=cache_folder,
                     ignore_download_archive=ignore_download_archive,
                     play=play, verbose=verbose, archive_file=archive_file)
        print(" ")
