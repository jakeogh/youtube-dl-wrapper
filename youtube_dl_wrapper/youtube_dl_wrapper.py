#!/usr/bin/env python3


import sys
import os
import time
import re
import glob
import string
import io
from shutil import get_terminal_size
from contextlib import redirect_stderr
from contextlib import redirect_stdout
import sre_constants
from pathlib import Path
from random import shuffle
import random
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
from kcl.clipboardops import get_clipboard
from iridb.atoms import UrlparseResult
from redisfilter.redisfilter import is_excluded

ic.configureOutput(includeContext=True)
ic.lineWrapWidth, _ = get_terminal_size((80, 20))

global DELAY_MULTIPLIER
DELAY_MULTIPLIER = random.random() / 2

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


# from @altendky
class Tee:
    def __init__(self, *targets):
        self.targets = targets

    def write(self, b):
        for target in self.targets:
            target.write(b)

    def flush(self):
        for target in self.targets:
            target.flush()

    def close(self):
        for target in self.targets:
            target.close()

    def isatty(self):
        return True

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


class NoVideoException(ValueError):
    pass


class TooManyRequestsException(ValueError):
    pass


class AlreadyDownloadedException(ValueError):
    pass


class RedsiSkipException(ValueError):
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


def is_direct_link_to_video(url):
    #https://twitter.com/TheUnitedSpot1/status/1263190701996556288
    url = UrlparseResult(url)
    if url.domain_psl() == "youtu.be":
        if len(url) == 28:
            return True
    if url.domain_psl() == "youtube.com":
        if len(url) == 43:
            return True
    #if url.domain_psl() == "twitter.com":
    #    ic(dir(url))
    #    import IPython; IPython.embed()


def is_direct_link_to_playlist(url):
    if url.startswith("https://www.youtube.com/playlist?list="):
        return True


def is_direct_link_to_channel(url):
    if url.startswith("https://www.youtube.com/channel"):
        return True


def is_direct_link_to_user(url):
    if url.startswith("https://www.youtube.com/user"):
        return True


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


def get_playlist_for_channel(url, verbose, debug):
    ydl = YoutubeDL()
    ie = YoutubeChannelIE(ydl)
    info = ie.extract(url)
    if debug:
        ic(info)
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


def generate_download_options(*,
                              verbose,
                              debug,
                              cache_dir=False,
                              ignore_download_archive=True,
                              play=False,
                              archive_file=False,
                              notitle=False):
    play_command = ' '.join(VIDEO_CMD) + ' {}'
    queue_command = ' '.join(QUEUE_CMD) + ' {}'

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
        'user_agent': "Mozilla/5.0 (X11; Linux x86_64; rv:72.0) Gecko/20100101 Firefox/72.0",
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

    #if verbose:
    ydl_ops['verbose'] = True  # must be set to scrape tracebacks

    if not ignore_download_archive:
        ydl_ops['download_archive'] = archive_file

    return ydl_ops


def convert_url_to_redirect(*, url, ydl_ops, verbose, debug, redis_skip):
    if verbose:
        ic(url)
    json_info = get_json_info(url=url, ydl_ops=ydl_ops, verbose=verbose, debug=debug, redis_skip=redis_skip)

    try:
        if json_info['extractor'] in ['generic']:
            if debug:
                ic(json_info['extractor'])
            try:
                return json_info['url']
            except KeyError:
                return url
    except TypeError as e:  # 'NoneType' object is not subscriptable
        if verbose:
            ic(e)
        return url
    else:
        return url


def convert_id_to_webpage_url(*, vid_id, ydl_ops, verbose, debug, redis_skip):
    if verbose:
        ic(vid_id)
    json_info = get_json_info(url=vid_id, ydl_ops=ydl_ops, verbose=verbose, debug=debug, redis_skip=redis_skip)
    webpage_url = json_info['webpage_url']
    if verbose:
        ic(webpage_url)
    return webpage_url


def convert_url_to_youtube_playlist(*, url, ydl_ops, verbose, debug, redis_skip):
    if verbose:
        ic(url)

    json_info = get_json_info(url=url, ydl_ops=ydl_ops, verbose=verbose, debug=debug, redis_skip=redis_skip)
    try:
        if json_info['extractor'] in ['youtube:user', 'youtube:channel']:
            playlist_url = json_info['url']
            if verbose:
                ic(json_info['extractor'])
                ic(playlist_url)
            return playlist_url
    except TypeError as e:  # 'NoneType' object is not subscriptable
        if verbose:
            ic(e)
        return url
    else:
        return url


def get_playlist_links(*, url, ydl_ops, verbose, debug, redis_skip):
    if verbose:
        ic(url)
    json_info = get_json_info(url=url, ydl_ops=ydl_ops, verbose=verbose, debug=debug, redis_skip=redis_skip)
    links = []

    try:
        if 'entries' in json_info.keys():
            for item in json_info['entries']:
                links.append((json_info['extractor'], item['url']))
    except (AttributeError, KeyError):  #  'NoneType' object has no attribute 'keys'
        raise NotPlaylistException

    if verbose:
        ic(links)
    if not links:
        raise NotPlaylistException

    return links


def get_json_info(*, url, ydl_ops, verbose, debug, redis_skip):
    ydl_ops['dumpjson'] = True
    ydl_ops['extract_flat'] = True
    #try:
    f_stderr = io.StringIO()
    f_stdout = io.StringIO()
    with redirect_stderr(f_stderr):
        with redirect_stdout(f_stdout):
            with YoutubeDL(ydl_ops) as ydl:
                json_info = ydl.extract_info(url, download=False)
    stderr_out = f_stderr.getvalue()
    stdout_out = f_stdout.getvalue()
    #ic(stderr_out)
    #ic(stdout_out)
    print(stderr_out)
    print(stdout_out)
    if debug:
        ic(json_info)
    if "youtube_dl.utils.ExtractorError" in stderr_out:
        raise NoVideoException
    if "<HTTPError 429: 'Too Many Requests'>" in stderr_out:
        raise TooManyRequestsException
    if "<HTTPError 404: 'Not Found'>" in stderr_out:
        raise NoVideoException

    #import IPython; IPython.embed()

    if json_info['extractor'] in ["youtube:channel", "youtube:user"]:  # (wrong for user) cant know the uploader yet unfortunatly
        return json_info

    try:
        redis_value_to_look_for = json_info['extractor'] + "/" + json_info['uploader']
    except KeyError:
        return json_info

    redis_value_to_look_for = redis_value_to_look_for.encode('utf8')
    if verbose:
        ic(redis_value_to_look_for)

    if is_excluded(byte_string=redis_value_to_look_for,
                   exclusions_key=redis_skip,
                   verbose=verbose,
                   debug=debug):
        raise RedsiSkipException

    return json_info


def download_url(*, url, ydl_ops, retries, verbose, debug, redis_skip, json_info=None, current_try=1):

    # wrong spot to do this...
    global DELAY_MULTIPLIER
    assert url
    response = None
    delay = 10

    while response == None:
        try:
            response = requests.head(url)
            if debug:
                ic(response.headers)
        except Exception as e:
            if current_try == 1:
                ic(delay, url, e)
            else:
                ic(delay)
            response = None
            time.sleep(delay)
            delay = delay + (delay * DELAY_MULTIPLIER)

    if not json_info:
        json_info = get_json_info(url=url,
                                  ydl_ops=ydl_ops,
                                  verbose=verbose,
                                  debug=debug,
                                  redis_skip=redis_skip)
        if debug:
            ic(json_info)
            #import IPython; IPython.embed()

    f_stderr = io.StringIO()
    f_stdout = io.StringIO()
    with redirect_stderr(Tee(f_stderr, sys.__stderr__)):
        with redirect_stdout(Tee(f_stdout, sys.__stdout__)):
            with YoutubeDL(ydl_ops) as ydl:
                thing = ydl.download([url])
                #ic(thing)
    stderr_out = f_stderr.getvalue()
    stdout_out = f_stdout.getvalue()
    if verbose:
        ic(stderr_out)
        ic(stdout_out)
    print(stderr_out)
    print(stdout_out)
    if "<HTTPError 404: 'Not Found'>" in stderr_out:
        raise NoVideoException
    if "has already been recorded in archive" in stdout_out:
        raise AlreadyDownloadedException

    #with YoutubeDL(ydl_ops) as ydl:
    #    thing = ydl.download([url])
    #    ic(thing)
    if (int(thing) == 1) or ("<urlopen error timed out>" in stderr_out):
        ic(current_try)
        if current_try <= retries:
            download_url(url=url,
                         ydl_ops=ydl_ops,
                         retries=retries,
                         verbose=verbose,
                         debug=debug,
                         redis_skip=redis_skip,
                         current_try=current_try + 1)


def construct_url_from_id(*, vid_id, extractor, verbose, debug):
    if verbose:
        ic(vid_id)
    if extractor in ["youtube:playlist", "youtube:search_url"]:
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


def youtube_dl_wrapper(*,
                       url,
                       id_from_url,
                       ignore_download_archive,
                       extract_urls,
                       destdir,
                       archive_file,
                       redis_skip=b"mpv:queue:exclude#",
                       retries=4,
                       play=False,
                       verbose=False,
                       debug=False):

    destdir = Path(os.path.expanduser(destdir))
    archive_file = Path(os.path.expanduser(archive_file))

    ic(verbose)
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
                                                 debug=debug,
                                                 archive_file=archive_file)

    ydl_ops_notitle = generate_download_options(cache_dir=cache_folder,
                                                ignore_download_archive=ignore_download_archive,
                                                play=play,
                                                verbose=verbose,
                                                debug=debug,
                                                archive_file=archive_file,
                                                notitle=True)

    url_set = set()

    if is_direct_link_to_video(url):
        eprint("its a direct link to a video, adding to set")
        url_set.add(url)
    else:
        eprint("not a direct link to a video")
        # step 0, convert non-url to url
        if not (url.startswith('https://') or url.startswith('http://')):
            eprint("attempting to convert", url, "to url")
            url_from_id = convert_id_to_webpage_url(vid_id=url,
                                                    ydl_ops=ydl_ops_standard,
                                                    verbose=verbose,
                                                    redis_skip=redis_skip,
                                                    debug=debug)
            if verbose:
                ic(url_from_id)
            if id_from_url != url:
                url_set.add(url_from_id)

        else:
            # step 2, expand redirects
            if not (is_direct_link_to_channel(url) or is_direct_link_to_playlist(url) or is_direct_link_to_user(url)):
                eprint("not a direct link to a channel or playlist, checking for a redirect")
                url_redirect = convert_url_to_redirect(url=url,
                                                       ydl_ops=ydl_ops_standard,
                                                       verbose=verbose,
                                                       redis_skip=redis_skip,
                                                       debug=debug)
                if verbose:
                    ic(url_redirect)
                url_set.add(url_redirect)
                url_set.add(url)

            elif (is_direct_link_to_channel(url) or is_direct_link_to_user(url)):
                eprint("converting channel or user to playlist")
                playlist_url = convert_url_to_youtube_playlist(url=url,
                                                               ydl_ops=ydl_ops_standard,
                                                               verbose=verbose,
                                                               redis_skip=redis_skip,
                                                               debug=debug)
                if verbose:
                    ic(playlist_url)
                url_set.add(playlist_url)
                #url_set.add(url)
            elif is_direct_link_to_playlist(url):
                eprint("direct link to playlist, adding to download set")
                url_set.add(url)
            else:
                eprint("not a direct link to channel or playlist, no idea, adding to download set anyway")
                url_set.add(url)

    larger_url_set = set()
    for index, url in enumerate(url_set):
        # step 1, expand playlists
        if not is_direct_link_to_video(url):
            try:
                for extractor, vid_id in get_playlist_links(url=url,
                                                            ydl_ops=ydl_ops_standard,
                                                            verbose=verbose,
                                                            redis_skip=redis_skip,
                                                            debug=debug):
                    try:
                        constructed_url = construct_url_from_id(vid_id=vid_id, extractor=extractor, verbose=verbose, debug=debug)
                        larger_url_set.add(constructed_url)
                    except NotImplementedError as e:
                        ic(e)
                        larger_url_set.add(url)

            except NotPlaylistException:
                eprint("Not a playlist, adding url to set directly")
                larger_url_set.add(url)
        else:
            larger_url_set.add(url)

    url_set_len = len(larger_url_set)
    for index, url in enumerate(larger_url_set):
        if verbose:
            ic(index, url)

        eprint("{} of {}".format(index + 1, url_set_len), url)

        try:
            url_id, extractor = extract_id_from_url(url)
        except NoIDException:
            extractor = None

        if extractor in ['twitter'] or url.startswith('https://t.co/'):
            download_url(url=url,
                         ydl_ops=ydl_ops_notitle,
                         retries=retries,
                         verbose=verbose,
                         redis_skip=redis_skip,
                         debug=debug)

        else:
            download_url(url=url,
                         ydl_ops=ydl_ops_standard,
                         retries=retries,
                         verbose=verbose,
                         redis_skip=redis_skip,
                         debug=debug)

        print()
        continue


@click.command()
@click.argument('urls', nargs=-1)
@click.option('--id-from-url', is_flag=True)
@click.option('--ignore-download-archive', is_flag=True)
@click.option('--play', is_flag=True)
@click.option('--extract-urls', is_flag=True)
@click.option('--tries', type=int, default=4)
@click.option('--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
@click.option('--redis-skip-uploader-set', is_flag=False, required=False, type=bytes, default=b'mpv:queue:exclude#')
@click.option('--destdir', is_flag=False, required=False, default='~/_youtube')
@click.option('--archive-file', is_flag=False, required=False, default='~/.youtube_dl.cache')
def cli(urls,
        id_from_url,
        ignore_download_archive,
        play,
        extract_urls,
        tries,
        verbose,
        debug,
        destdir,
        redis_skip_uploader_set,
        archive_file):

    if not urls:
        ceprint("no args, checking clipboard for urls")
        urls = get_clipboard_iris(verbose=debug)
        if verbose:
            ic(urls)

    if not urls:
        urls = get_clipboard(verbose=debug)
        urls = [urls]

    urls = list(urls)
    shuffle(urls)
    for url in urls:
        if url.startswith("http://www.youtube.com/"):
            url.replace("http://www.youtube.com/", "https://www.youtube.com/")
        if url.startswith("http://youtube.com/"):
            url.replace("http://youtube.com/", "https://youtube.com/")

    # https://m.youtube.com/watch?v=durcHyxpFT4

    ic(urls)
    for index, url in enumerate(urls):
        if verbose:
            ic(index, url)
        eprint('(outer) (' + str(index + 1), "of", str(len(urls)) + '):', url)

        if url.startswith("file://"):
            continue

        try:
            result = \
                youtube_dl_wrapper(url=url,
                                   id_from_url=id_from_url,
                                   ignore_download_archive=ignore_download_archive,
                                   play=play,
                                   retries=tries,
                                   extract_urls=extract_urls,
                                   redis_skip=redis_skip_uploader_set,
                                   verbose=verbose,
                                   debug=debug,
                                   destdir=destdir,
                                   archive_file=archive_file)
            ic(result)
        except NoVideoException:
            eprint("No Video at URL:", url)
        except AlreadyDownloadedException:
            eprint("Video already downloaded", url)
        except RedsiSkipException:
            eprint("RedsiSkipException", url)


