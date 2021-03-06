import requests
import json
import re
import urllib
from multiprocessing.pool import ThreadPool
from struct import *
import time
import os

from config import BLOCK_SIZE, FILE_UPLOAD_THREADS_NUM
import errno

CACHE_DIR = "/var/cache/snfs"


def get_link_by_id(id):
    headers = {
        'origin': 'https://vk.com',
        'accept-encoding': 'gzip, deflate, br',
        'x-requested-with': 'XMLHttpRequest',
        'accept-language': 'ru-RU,ru;q=0.8,en-US;q=0.6,en;q=0.4',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.100 Safari/537.36',
        'content-type': 'application/x-www-form-urlencoded',
        'accept': '*/*',
        'referer': 'https://vk.com/audios396547478',
        'authority': 'vk.com',
        'cookie': 'remixdt=0; remixtst=6a6160ae; remixsid=e08c978875d6955f5cf30f7edfcffb6e5197f9c448626357437a5; remixsslsid=1; remixseenads=2; remixlang=0; remixrefkey=8a3de8954c2156ec2a; remixflash=23.0.0; remixscreen_depth=24; remixcurr_audio=396547478_456239053',
    }
    data = {
        'act': 'reload_audio',
        'al': '1',
        'ids': id
    }
    # print data
    r = requests.post('https://vk.com/al_audio.php', headers=headers, data=data)
    response = re.search('\[\[.+\]\]', r.text)
    response = json.loads(response.group(0))
    return response


def splitFile(inputFile):
    chunkSize = 956
    header = "\xff\xfb\xe4\x44"
    f = open(inputFile, 'rb')
    data = f.read()
    f.close()

    bytes = len(data)
    if inputFile.split("/")[-1] == "tree":
        print hex(bytes)
        data = pack('>i', bytes) + data

    noOfChunks = bytes / chunkSize
    if (bytes % chunkSize):
        noOfChunks += 1

    chunkNames = []
    res = ''
    for i in range(0, bytes + 1, chunkSize):
        fn1 = "chunk%s.mp3" % i
        res = res + header + data[i:i + chunkSize]
        if (len(data) - i) < chunkSize or 1048320 - len(res) < chunkSize:
            # res = res + header + data[i:len(data)]
            f = open('/tmp/' + fn1, 'wb')
            res_len = len(res)
            for j in range(0, (1048320 - res_len) / 960):
                res = res + header + "\x00" * 956
            res = res + "\x00" * (1048320 - len(res))
            f.write(res)
            f.close()
            res = ''
            chunkNames.append(fn1)
    return chunkNames


access_token = "4f050c2ec93a5ed968d23d3358d220632ecdbfe9c34beb95971bb05acdd3e75dd8ce3a181bdf181b9a665"


# 4 is OK. Occasional errors if use more
def upload_to_vk(array, threads_num=FILE_UPLOAD_THREADS_NUM):
    pool = ThreadPool(processes=threads_num)
    res = pool.map(upload_to_vk_single, array)
    return res


def upload_to_vk_single(fname):
    request_url = "https://api.vk.com/method/audio.getUploadServer" + "?access_token=" + access_token
    r = requests.get(request_url)
    url_to_upload = json.loads(r.text)['response']['upload_url']
    files = {'file': (fname, open('/tmp/' + fname, 'rb'), 'multipart/form-data', {'Expires': '0'})}
    r = requests.post(url_to_upload, files=files)
    response = json.loads(r.text)
    request_url = "https://api.vk.com/method/audio.save" + "?access_token=" + access_token
    payload = {'server': response['server'], 'audio': response['audio'], 'hash': response['hash'],
               'artist': "SSNSNERPONE", 'title': time.strftime('%Y%m%d-%H%M%S')}
    r = requests.get(request_url, params=payload)
    response = json.loads(r.text)
    print response
    #return fname, int(fname.strip('chunk').rstrip('.mp3')), str(response['response']['owner_id']) + "_" + str(response['response']['aid'])
    # no need to restore order the files were uploaded in?
    return str(response['response']['owner_id']) + "_" + str(response['response']['aid'])


def download_from_vk(tree=False, *args, **kwargs):
    # array = ['396547478_456239081', '396547478_456239082', '396547478_456239083', '396547478_456239084', '396547478_456239085', '396547478_456239086', '396547478_456239087', '396547478_456239088', '396547478_456239089', '396547478_456239090', '396547478_456239091']
    if not tree:
        array = kwargs['blocks']
        size = kwargs['size']
        fullpath = CACHE_DIR + kwargs['fullpath']
        # create branch if not exists
        if not os.path.exists(os.path.dirname(fullpath)):
            try:
                os.makedirs(os.path.dirname(fullpath))
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
        # append result to the file
        f = open(fullpath, 'ab')
    else:
        array = get_id_of_main_inode(hash=True)
        tree_raw = ''

    for i in array:
        response = get_link_by_id(i)
        data = ""
        for j in response:
            r = requests.get(j[2], stream=True)
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    data = data + chunk
            bytes = len(data)
            chunkSize = 960
            res = ''
            for k in range(0, bytes, chunkSize):
                res = res + data[k + 4:k + chunkSize]
            if not tree:
                if size < BLOCK_SIZE:
                    f.write(res[:size])
                else:
                    size -= BLOCK_SIZE
                    f.write(res)
            else:
                tree_raw += res
    if not tree:
        f.close()
    else:
        size = unpack(">i", tree_raw[:4])[0]
        return tree_raw[4:4 + size]


def get_id_of_main_inode(hash=False):
    album_id = 81678642
    headers = {
        'origin': 'https://vk.com',
        'accept-encoding': 'gzip, deflate, br',
        'x-requested-with': 'XMLHttpRequest',
        'accept-language': 'ru-RU,ru;q=0.8,en-US;q=0.6,en;q=0.4',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.100 Safari/537.36',
        'content-type': 'application/x-www-form-urlencoded',
        'accept': '*/*',
        'referer': 'https://vk.com/audios396547478',
        'authority': 'vk.com',
        'cookie': 'remixlang=0; remixdt=0; remixtst=e68e8382; remixsid=1a31753fc52162115c7376bcb5b882ed74dd5506f570b911c3795; remixsslsid=1; remixseenads=2; remixcurr_audio=396547478_456239096; remixflash=23.0.0; remixscreen_depth=24',
    }

    data = {
        'act': 'load_silent',
        'al': '1',
        'album_id': '81678642',
        'band': 'false',
        'owner_id': '396547478'
    }

    r = requests.post('https://vk.com/al_audio.php', headers=headers, data=data)
    response = re.search('\[\[.+\]\]', r.text)
    response = reversed(json.loads(response.group(0)))

    answer = []
    if hash == True:
        for i in response:
            answer.append(str(i[1]) + "_" + str(i[0] + "_" + str(i[13].split("/")[1])))
    else:
        for i in response:
            answer.append(str(i[1]) + "_" + str(i[0]))
    return answer


def upload_main_inode(tree):
    f = open("/tmp/tree", 'wb')
    f.write(tree)
    f.close()
    audio = get_id_of_main_inode(hash=True)

    album_id = 81678642

    ids = upload_to_vk(splitFile("/tmp/tree"))
    print ids
    for i in audio:
        i = i.split("_")
        headers = {
            'origin': 'https://vk.com',
            'accept-encoding': 'gzip, deflate, br',
            'x-requested-with': 'XMLHttpRequest',
            'accept-language': 'ru-RU,ru;q=0.8,en-US;q=0.6,en;q=0.4',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.100 Safari/537.36',
            'content-type': 'application/x-www-form-urlencoded',
            'accept': '*/*',
            'referer': 'https://vk.com/audios396547478?album_id=81678642',
            'authority': 'vk.com',
            'cookie': 'remixlang=0; remixdt=0; remixtst=e68e8382; remixsid=1a31753fc52162115c7376bcb5b882ed74dd5506f570b911c3795; remixsslsid=1; remixseenads=2; remixcurr_audio=396547478_456239094; remixflash=23.0.0; remixscreen_depth=24',
        }

        data = {
            'act': 'delete_audio',
            'aid': i[1],
            'al': '1',
            'hash': i[2],
            'oid': i[0],
            'restore': '0'
        }
        print data
        r = requests.post('https://vk.com/al_audio.php', headers=headers, data=data)

    print r.text

    for i in ids:
        headers = {
            'origin': 'https://vk.com',
            'accept-encoding': 'gzip, deflate, br',
            'x-requested-with': 'XMLHttpRequest',
            'accept-language': 'ru-RU,ru;q=0.8,en-US;q=0.6,en;q=0.4',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.100 Safari/537.36',
            'content-type': 'application/x-www-form-urlencoded',
            'accept': '*/*',
            'referer': 'https://vk.com/audios396547478',
            'authority': 'vk.com',
            'cookie': 'remixlang=0; remixdt=0; remixtst=e68e8382; remixsid=1a31753fc52162115c7376bcb5b882ed74dd5506f570b911c3795; remixsslsid=1; remixseenads=2; remixcurr_audio=396547478_456239096; remixflash=23.0.0; remixscreen_depth=24',
        }

        data = {
            'act': 'a_move_to_album',
            'al': '1',
            'album_id': '81678642',
            'audio_id': i.split("_")[1],
            'hash': '7575e1db51579d5ddc'
        }
        print data
        requests.post('https://vk.com/al_audio.php', headers=headers, data=data)
        os.remove("/tmp/tree")
