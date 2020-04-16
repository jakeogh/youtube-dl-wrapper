#!/usr/bin/env python3


import copy
import os
import time
import re
import glob
import string
import io
import sre_constants
from contextlib import redirect_stdout
from random import shuffle
from icecream import ic
import requests
import click
from youtube_dl.extractor import YoutubeChannelIE
from youtube_dl.compat import compat_expanduser
from youtube_dl.extractor import gen_extractors
from youtube_dl import YoutubeDL
from kcl.printops import ceprint
from kcl.printops import eprint
from kcl.fileops import points_to_data
from kcl.clipboardops import get_clipboard_iris


extractors = gen_extractors()
QUEUE_CMD = ['/home/cfg/redis/types/list/rpush', 'mpv:queue#']
#FSINDEX_CMD = ['/usr/bin/fsindex', 'create', 'record']
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
FILE_TEMPLATE_TW = '%(extractor)s' + '/' + '%(uploader)s' + '/' + "%(uploader_id)s__%(upload_date)s__%(id)s.%(ext)s"

MAX_TRIES = 3


def is_non_zero_file(fpath):
    if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
        return True
    return False


class NoIDException(ValueError):
    pass


class NoMatchException(ValueError):
    pass

class NotPlaylistException(ValueError):
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
        except IndexError:
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


def get_filename_for_url(*, url, ydl_ops):
    ic(url)
    ydl_ops['forcefilename'] = True
    ydl_ops['skip_download'] = True
    ydl_ops['quiet'] = True
    f = io.StringIO()

    with redirect_stdout(f):
        with YoutubeDL(ydl_ops) as ydl:
            ydl.download([url])
        out = f.getvalue()

    if out:
        ic(out)
        return out

    raise ValueError


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


def generate_download_options(*, cache_dir=False, ignore_download_archive=True, play=False, verbose=False, archive_file=False, notitle=False):
    play_command = ' '.join(VIDEO_CMD) + ' {}'
    queue_command = ' '.join(QUEUE_CMD) + ' {}'
    #fsindex_command = ' '.join(FSINDEX_CMD) + ' {}'

    if play:
        #exec_cmd = fsindex_command + ' ; ' + queue_command + ' ; ' + play_command + ' & '
        exec_cmd = queue_command + ' ; ' + play_command + ' & '
    else:
        exec_cmd = queue_command

    #ceprint("exec_cmd:", exec_cmd)
    ydl_ops = {
        'socket_timeout': 60,
        'ignoreerrors': True,
        'continuedl': True,
        'retries': 125,
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
        if notitle:
            ydl_ops['outtmpl'] = cache_dir + '/sources/' + FILE_TEMPLATE_TW
        else:
            ydl_ops['outtmpl'] = cache_dir + '/sources/' + FILE_TEMPLATE
    else:
        if notitle:
            ydl_ops['outtmpl'] = FILE_TEMPLATE_TW
        else:
            ydl_ops['outtmpl'] = FILE_TEMPLATE

    if verbose:
        ydl_ops['verbose'] = True

    if not ignore_download_archive:
        ydl_ops['download_archive'] = archive_file

    return ydl_ops


def convert_url_to_playlist(url, ydl_ops, verbose):
    ydl_ops['dumpjson'] = True
    ydl_ops['extract_flat'] = True
    #try:
    with YoutubeDL(ydl_ops) as ydl:
        json_info = ydl.extract_info(url, download=False)
    if verbose:
        ic(json_info)

    if json_info['extractor'] == 'youtube:user':
        if verbose:
            ic(json_info['extractor'])
        return json_info['url']
    else:
        return url


def get_playlist_links(*, url, ydl_ops, verbose):
    url = convert_url_to_playlist(url, ydl_ops, verbose)
    links = []
    ydl_ops['dumpjson'] = True
    ydl_ops['extract_flat'] = True
    #try:
    with YoutubeDL(ydl_ops) as ydl:
        json_info = ydl.extract_info(url, download=False)
    if verbose:
        ic(json_info)

    if 'entries' in json_info.keys():
        for item in json_info['entries']:
            links.append((json_info['extractor'], item['url']))
    #except Exception as e:
    #    ic(e)
    #if not links:
    #    links.append((json_info['extractor'], json_info['id']))

    if verbose:
        ic(links)
    if not links:
        raise NotPlaylistException

    return links


def download_url(*, url, ydl_ops):
    assert url
    response = None
    while response == None:
        try:
            response = requests.head(url)
            ic(response.headers)
        except Exception as e:
            ic(e)
            response = None
            time.sleep(1)

    with YoutubeDL(ydl_ops) as ydl:
        thing = ydl.download([url])
        #ic(dir(ydl))
        #ic(ydl.in_download_archive(ydl_ops))
        ic(thing)


def construct_url_from_id(*, vid_id, extractor):
    if extractor == "youtube:playlist":
        return "https://www.youtube.com/watch?v={}".format(vid_id)
    if extractor == "BitChute":
        return "https://www.bitchute.com/video/{}".format(vid_id)
    raise NotImplementedError("Unknkown extractor: {}".format(extractor))


def construct_youtube_url_from_id(ytid):
    if len(ytid) == 11:
        allowed = set(string.ascii_lowercase + string.ascii_uppercase + string.digits + '_' + '-')
        if set(ytid) <= allowed:
            ceprint("found bare youtube id:", ytid)
            url = 'https://www.youtube.com/watch?v=' + ytid
            return url
    return False


def look_for_output_file_variations(output_file):
    output_file_no_ext = ".".join(output_file.split('.')[:-1])
    extensions = ['webm', 'mp4', 'mkv', 'mxf']
    for ext in extensions:
        file_to_look_for = output_file_no_ext + '.' + ext
        ceprint("looking for:", file_to_look_for)
        if points_to_data(file_to_look_for):
            return True
    return False


@click.command()
@click.argument('urls', nargs=-1)
@click.option('--id-from-url', is_flag=True)
@click.option('--ignore-download-archive', is_flag=True)
@click.option('--play', is_flag=True)
@click.option('--extract-urls', is_flag=True)
@click.option('--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
@click.option('--destdir', is_flag=False, required=False, default='~/_youtube')
@click.option('--archive-file', is_flag=False, required=False, default='~/.youtube_dl.cache')
def youtube_dl_wrapper(urls, id_from_url, ignore_download_archive, play, extract_urls, verbose, debug, destdir, archive_file):
    ic(verbose)
    if not urls:
        ceprint("no args, checking clipboard for urls")
        urls = get_clipboard_iris(verbose=debug)
        if verbose:
            ic(urls)

    urls = list(urls)
    shuffle(urls)
    ic(urls)
    cache_folder = compat_expanduser(destdir)
    try:
        os.chdir(cache_folder)
    except FileNotFoundError:
        print("Unable to os.chdir() to", cache_folder, "Press enter to retry.")
        input('pause')
        os.chdir(cache_folder)

    ydl_ops_standard = generate_download_options(cache_dir=cache_folder,
                                                 ignore_download_archive=ignore_download_archive,
                                                 play=play,
                                                 verbose=verbose,
                                                 archive_file=archive_file)
    ydl_ops_notitle = generate_download_options(cache_dir=cache_folder,
                                                ignore_download_archive=ignore_download_archive,
                                                play=play,
                                                verbose=verbose,
                                                archive_file=archive_file,
                                                notitle=True)

    url_set = set([])
    for index, url in enumerate(urls):
        eprint('(outer) (' + str(index + 1), "of", str(len(urls)) + '):', url)


        # step 1, expand playlists
        try:
            for extractor, vid_id in get_playlist_links(url=url, ydl_ops=ydl_ops_standard, verbose=verbose):
                try:
                    constructed_url = construct_url_from_id(vid_id=vid_id, extractor=extractor)
                    url_set.add(constructed_url)
                except NotImplementedError as e:
                    ic(e)
                    url_set.add(url)

        except NotPlaylistException:
            eprint("Not a playlist, adding url to set directly")
            url_set.add(url)


    url_set_len = len(url_set)
    for index, url in enumerate(url_set):
        eprint("{} of {}".format(index, url_set_len), url)

        url_id, extractor = extract_id_from_url(url)

        if extractor in ['twitter'] or url.startswith('https://t.co/'):
            download_url(url=url, ydl_ops=ydl_ops_notitle)

        else:
            download_url(url=url, ydl_ops=ydl_ops_standard)

        print()
        continue


        # disabled, hooktube is handeled automatically now
        #try:
        #    url_id, extractor = extract_id_from_url(url)

        #except NoIDException:
        #    #ceprint("url:", url)
        #    if 'hooktube.com' in url:
        #        hooktube_id = url.split('/')[-1]
        #        url = 'https://youtube.com/watch?v=' + hooktube_id
        #        ceprint("url:", url)
        #        urlid, extractor = extract_id_from_url(url)
        #    else:
        #        urlid = None
        #        extractor = None

        #max_tries = 11
        ##ceprint("extractor:", extractor)
        ##ceprint("str(extractor):", str(extractor))
        ##ceprint("type(extractor):", type(extractor))
        #if extractor in ['youtube:channel']:
        #    url = get_playlist_for_channel(url)
        #    url_id, extractor = extract_id_from_url(url)  # re-get now that user is converted to channel playlist

        ##if extractor in ['youtube:playlist', 'youtube:user']:
        #if extractor in ['youtube:playlist']:
        #    playlist_links = get_playlist_links(url=url, ydl_ops=copy.copy(ydl_ops))
        #    for plindex, plurl in enumerate(playlist_links):
        #        tries = 0
        #        eprint('(' + str(plindex+1), "of", str(len(playlist_links)) + '):', url)
        #        output_file = get_filename_for_url(url=plurl, ydl_ops=copy.copy(ydl_ops))
        #        ic(output_file)

        #        while not look_for_output_file_variations(output_file):
        #            tries += 1
        #            if tries > max_tries:
        #                ceprint("tried", max_tries, "times, skipping")
        #                break
        #            else:
        #                ic(tries)
        #                ic(output_file)
        #                download_url(url=plurl, ydl_ops=copy.copy(ydl_ops))
        #elif extractor in ['twitter'] or url.startswith('https://t.co/'):
        #    ydl_ops = generate_download_options(cache_dir=cache_folder,
        #                                        ignore_download_archive=ignore_download_archive,
        #                                        play=play,
        #                                        verbose=verbose,
        #                                        archive_file=archive_file,
        #                                        notitle=True)
        #    download_url(url=url, ydl_ops=ydl_ops)

        #else:
        #    ceprint("skipped looking for output file")
        #    download_url(url=url, ydl_ops=ydl_ops)

        #print(" ")

