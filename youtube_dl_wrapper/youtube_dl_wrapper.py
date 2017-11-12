#!/usr/bin/env python

import sys
import sh
import os
import re
import glob
import subprocess
import youtube_dl
import time

from youtube_dl.compat import compat_expanduser

from youtube_dl.extractor import gen_extractors
extractors = gen_extractors()

cache_folder = compat_expanduser('~/_youtube')
video_command = [compat_expanduser('~/cfg/appwrappers/mplayer')]
video_command_loop = ['/usr/bin/mpv', '-fs', '-loop', '0']
video_command_audio_only = ['/usr/bin/mpv', '-fs', '--no-video']
video_command_audio_only_loop = ['/usr/bin/mpv', '-fs', '-vo', 'none', '-loop', '0']
downloaded_video_list = []

def is_non_zero_file(fpath):
    if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
        return True
    return False

def extract_id_from_url(url):
    for e in extractors:
        try:
            regex = e._VALID_URL
            id = re.match(regex, url, re.VERBOSE).groups()[-1]
#            print("using extractor:", e.IE_NAME) #youtube:user
#            print(dir(e))
            if 'youtube' in e.IE_NAME:
                try:
                    if len(id) != 11:
                        return False
                except TypeError:
                    return False
            return id
        except re.error:
            pass
        except AttributeError:
            pass
        except IndexError:
            pass
    return False

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
    try:
        pre_matches = glob.glob(cache_folder + '/*' + video_id + '*')
        matches = []
        for match in pre_matches:
            if match.endswith('.description'):
                continue
            if match.endswith('.json'):
                continue
            if match.endswith('.part'):
                continue
            match_ending = match.split(video_id)[-1]
            if len(match_ending.split('.')) > 1:
                continue
            matches.append(match)
        if matches:
            return matches
        return False
    except:
        return False

def process_url_list(url_list):
    ydl_opts = {
        'verbose': True,
        'forcefilename': True,
        'socket_timeout': 30,
        'outtmpl': "%(uploader)s__%(uploader_id)s__%(upload_date)s__%(title)s__%(extractor)s__%(id)s.%(ext)s",
        'ignoreerrors': True,
        'continue': True,
        'retries': 10,
        'fragment_retries': 10,
        'writedescription': True,
        'writeinfojson': True,
        'allsubtitles': True,
        'logger': MyLogger(),
    }

#        'playlist': True,

    for url in url_list:
        if len(url) == 0:
            continue
        else:
            print("url:", url)

        id_from_url = extract_id_from_url(url)
        print("id_from_url:", id_from_url)
        if not id_from_url:
            id_from_url = download_id_for_url(url)

        existing_files = check_if_video_exists_by_video_id(id_from_url)
        if not existing_files:
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


                files = check_if_video_exists_by_video_id(id_from_url)
                if files:
                    for file in files:
                        downloaded_video_list.append(file)
        else:
            for file in existing_files:
                downloaded_video_list.append(file)


def play_media(video_list):
    for file in video_list:
        pause("\nPress any key to play: " + str(file))
        play = "y"
        while play.lower().startswith( "y"):
            if play.lower() == 'yy':
                mplayer_audio_only(file)
            elif play.lower() == 'yyy':
                mplayer_audio_only_loop(file)
            elif play.lower() == 'yyyy':
                mplayer_loop(file)
            else:
                mplayer(file)
            print("Done playing.")
            play = input("\nEnter y to replay (yy to play audio only, yyy to loop audio, yyyy to loop a/v): ")


def mplayer(file):
    cmd = sh.Command(video_command[0])
    for arg in video_command[1:]:
        cmd = cmd.bake(arg)
    cmd(file)

def mplayer_loop(file):
    cmd = sh.Command(video_command_audio_only_loop[0])
    for arg in video_command_loop[1:]:
        cmd = cmd.bake(arg)
    cmd(file)

def mplayer_audio_only(file):
    cmd = sh.Command(video_command_audio_only[0])
    for arg in video_command_audio_only[1:]:
        cmd = cmd.bake(arg)
    cmd(file)

def mplayer_audio_only_loop(file):
    cmd = sh.Command(video_command_audio_only_loop[0])
    for arg in video_command_audio_only_loop[1:]:
        cmd = cmd.bake(arg)
    cmd(file)

def pause(message="Press any key to continue"):
    print(message)
    input()

def youtube_dl_wrapper(cache_folder=cache_folder, video_command=video_command, play=True):
    if not is_non_zero_file(video_command[0]):
        video_command = ['/usr/bin/mpv', '-fs']

    url_list = []
    if len(sys.argv) == 1:
        print("no args, checking clipboard for urls")
        url_list = get_clipboard_urls()

    else:
        for item in sys.argv[1:]:
            if item == 'play':
                play = True
            else:
                url_list.append(item)

    try:
        os.chdir(cache_folder)
    except:
        print("Unable to os.chdir() to", cache_folder, "Press enter to retry.")
        pause()
        try:
            os.chdir(cache_folder)
        except:
            print("Unable to os.chdir() to", cache_folder, "Exiting.")
            os._exit(1)


    print("url_list:", url_list)
    process_url_list(url_list)
    print(" ")
    print(downloaded_video_list)
    play_media(downloaded_video_list)

    if play:
        pause("\nPress any key to exit")

if __name__ == '__main__':
    youtube_dl_wrapper(cache_folder)



