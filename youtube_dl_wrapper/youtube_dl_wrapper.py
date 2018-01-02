#!/usr/bin/env python

import click
#import sys
import sh
import os
import re
import glob
import subprocess
import youtube_dl
import time

from youtube_dl.compat import compat_expanduser
from youtube_dl.extractor import gen_extractors
from kcl.printops import eprint

extractors = gen_extractors()

VIDEO_CMD = ['/usr/bin/mpv',
             '--cache-pause',
             '--hwdec=vdpau',
             '--cache-initial=75000',
             '--cache-default=275000']

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
    try:
        lsof_check = sh.grep(sh.lsof(), video_id)
    except:
        pass

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


def download_url(url, output_dir):
    assert url
    ydl_opts = {
        'verbose': False,
        'forcefilename': True,
        'socket_timeout': 30,
        'outtmpl': output_dir + "/%(uploader)s__%(uploader_id)s__%(upload_date)s__%(title)s__%(extractor)s__%(id)s.%(ext)s",
        'ignoreerrors': True,
        'continue': True,
        'retries': 20,
        'playlist': False,
        'fragment_retries': 10,
        'writedescription': True,
        'writeinfojson': True,
        'allsubtitles': True,
        'progress_with_newline': False,
        'logger': MyLogger(),
    }


    print("url:", url)
    id_from_url, extractor = extract_id_from_url(url)
    print("id_from_url:", id_from_url)
    if not id_from_url:
        id_from_url = download_id_for_url(url)

    assert id_from_url
    try:
        existing_file = check_if_video_exists_by_video_id(id_from_url)
    except NoMatchException:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            result = 1
            tries = 0
            while result != 0:
                try:
                    result = ydl.download([url])
                    print("try result:", result)
                except Exception as e: # annoying that YoutubeDL is not raising exceptions when it fails
                    print("Exception:", e)
                    print("result:", result)
                time.sleep(2)
                tries += 1
                if tries >= ydl_opts['retries']:
                    break

            existing_file = check_if_video_exists_by_video_id(id_from_url)

    downloaded_video_list.append(existing_file)
    return existing_file


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
@click.argument('uris', nargs=-1)
@click.option('--play', is_flag=True)
@click.option('--id-from-url', is_flag=True)
def youtube_dl_wrapper(uris, play, id_from_url, cache_folder=CACHE_FOLDER, video_command=VIDEO_CMD):
    if not uris:
        eprint("no args, checking clipboard for urls")
        uris = get_clipboard_urls()

    if id_from_url:
        print(download_id_from_url)
        quit(0)

    try:
        os.chdir(cache_folder)
    except:
        print("Unable to os.chdir() to", cache_folder, "Press enter to retry.")
        pause()
        os.chdir(cache_folder)

    for url in uris:
        print(url)
        video_id, video_extractor = extract_id_from_url(url)
        print("extractor:", video_extractor, "id:", video_id)
        output_dir = cache_folder + '/sources/' + video_extractor + '/' + video_id[0] + '/' + video_id[1]
        os.makedirs(output_dir, exist_ok=True)
        os.chdir(output_dir)
        video_file = download_url(url=url, output_dir=output_dir)
        assert video_file
        os.chdir(CACHE_FOLDER)

        print(" ")

    if play:
        play_media(downloaded_video_list)
        pause("\nPress any key to exit")
