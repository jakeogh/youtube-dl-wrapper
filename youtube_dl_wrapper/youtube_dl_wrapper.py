#!/usr/bin/env python

import click
import sh
import os
import re
import glob
import subprocess
import youtube_dl

from youtube_dl.compat import compat_expanduser
from youtube_dl.extractor import gen_extractors
from kcl.printops import eprint

extractors = gen_extractors()

VIDEO_CMD = ['/usr/bin/xterm',
             '-e',
             '/usr/bin/mpv',
             '--cache-pause',
             '--hwdec=vdpau',
             '--cache-initial=75000',
             '--cache-default=275000',
             '--pause']

QUEUE_CMD = ['/home/cfg/media/queue']

CACHE_FOLDER = compat_expanduser('~/_youtube')
VIDEO_CMD_LOOP = VIDEO_CMD + ['-fs', '-loop', '0']
VIDEO_CMD_AUDIO_ONLY = VIDEO_CMD + ['-fs', '--no-video']
VIDEO_CMD_AUDIO_ONLY_LOOP = VIDEO_CMD + ['-fs', '-vo', 'none', '-loop', '0']
downloaded_video_list = []


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
            id = re.match(regex, url, re.VERBOSE).groups()[-1]
            extractor = e.IE_NAME
#            print("using extractor:", e.IE_NAME) #youtube:user
            if 'youtube' in e.IE_NAME:
                try:
                    if len(id) != 11:
                        return False
                except TypeError:
                    return False
            return id, extractor
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


class MyLogger(object):
    def debug(self, msg):
        print(msg)
    def warning(self, msg):
        print(msg)
    def error(self, msg):
        print(msg)


def get_clipboard():
    clipboard_text = subprocess.Popen(["xclip", "-o"], stdout=subprocess.PIPE).stdout.read()
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
    eprint("pre_matches:", pre_matches)
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
        #if len(match_ending.split('.')) > 1:
        #    continue
        matches.append(match)
    if matches:
        eprint("matches:", matches)
        #assert len(matches) == 1
        return matches[0]
    raise NoMatchException


def download_url(url, cache_dir):
    assert url
    #exec_cmd = ' '.join(VIDEO_CMD) + ' {} &'
    exec_cmd = ' '.join(QUEUE_CMD) + ' {} &'
    ydl_opts = {
        'verbose': False,
        'forcefilename': True,
        'socket_timeout': 30,
        'outtmpl': cache_dir + '/sources/' + '%(extractor)s' +'/' + '%(uploader)s' + '/' + "%(uploader)s__%(uploader_id)s__%(upload_date)s__%(title)s__%(extractor)s__%(id)s.%(ext)s",
        'ignoreerrors': True,
        'continue': True,
        'retries': 20,
        'playlist': False,
        'fragment_retries': 10,
        'writedescription': True,
        'writeinfojson': True,
        'allsubtitles': True,
        'progress_with_newline': False,
        'postprocessors': [{
        'key': 'ExecAfterDownload',
        'exec_cmd': exec_cmd,
        }],
        'logger': MyLogger(),
    }

    print("url:", url)
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


def play_media(video_list):
    for infile in video_list:
        pause("\nPress any key to play: " + str(infile))
        play = "y"
        while play.lower().startswith("y"):
            if play.lower() == 'yy':
                mplayer_audio_only(infile)
            elif play.lower() == 'yyy':
                mplayer_audio_only_loop(infile)
            elif play.lower() == 'yyyy':
                mplayer_loop(infile)
            else:
                mplayer(infile)
            print("Done playing.")
            play = input("\nEnter y to replay (yy to play audio only, yyy to loop audio, yyyy to loop a/v): ")


def mplayer(infile):
    cmd = sh.Command(VIDEO_CMD[0])
    for arg in VIDEO_CMD[1:]:
        cmd = cmd.bake(arg)
    cmd(infile)


def mplayer_loop(infile):
    cmd = sh.Command(VIDEO_CMD_AUDIO_ONLY_LOOP[0])
    for arg in VIDEO_CMD_LOOP[1:]:
        cmd = cmd.bake(arg)
    cmd(infile)


def mplayer_audio_only(infile):
    cmd = sh.Command(VIDEO_CMD_AUDIO_ONLY[0])
    for arg in VIDEO_CMD_AUDIO_ONLY[1:]:
        cmd = cmd.bake(arg)
    cmd(infile)


def mplayer_audio_only_loop(infile):
    cmd = sh.Command(VIDEO_CMD_AUDIO_ONLY_LOOP[0])
    for arg in VIDEO_CMD_AUDIO_ONLY_LOOP[1:]:
        cmd = cmd.bake(arg)
    cmd(infile)


def pause(message="Press any key to continue"):
    print(message)
    input()


@click.command()
@click.argument('urls', nargs=-1)
@click.option('--play', is_flag=True)
@click.option('--id-from-url', is_flag=True)
def youtube_dl_wrapper(urls, play, id_from_url):
    if not urls:
        eprint("no args, checking clipboard for urls")
        urls = get_clipboard_urls()

    try:
        os.chdir(CACHE_FOLDER)
    except FileNotFoundError:
        print("Unable to os.chdir() to", CACHE_FOLDER, "Press enter to retry.")
        pause()
        os.chdir(CACHE_FOLDER)

    for url in urls:
        print(url)
        if id_from_url:
            print(download_id_for_url(url))
            continue
        download_url(url=url, cache_dir=CACHE_FOLDER)
        print(" ")
