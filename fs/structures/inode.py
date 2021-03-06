import datetime
import operator
import pickle
import uuid
from functools import reduce
from exceptions import *


class Inode(object):
    SOCIALS = {
        'VK': 1,
        'MixCloud': 2,
        'SoundCloud': 3
    }

    def __init__(self, size, blocks, m_time=datetime.datetime.now(), c_time=datetime.datetime.now(),
                 a_time=datetime.datetime.now()):
        self.id = int(uuid.uuid4().time_low)
        self.size = size
        self.blocks = blocks
        self.a_time = a_time
        self.m_time = m_time
        self.c_time = c_time

    def __str__(self):
        return str(self.id)


class Tree(object):
    def __init__(self):
        self.inodes = {'/': {}}

    def __str__(self):
        def tree_printer(tree, indent=0):
            for k, v in tree.iteritems():
                if isinstance(v, dict):
                    print '\t' * indent + str(k)
                    tree_printer(v, indent + 1)
                else:
                    print '\t' * indent + "%s %s" % (k, v)

        tree_printer(self.inodes)
        return ''

    @staticmethod
    def _find_path(mapList, tree):
        return reduce(operator.getitem, tree, mapList)

    @staticmethod
    def _path_dissect(path):
        path_components = ['/']
        if not path.startswith('/'):
            raise LookupError("Path must start with /")
        if path != '/':
            path_components += path.strip('/').split('/')
        return path_components

    def mkdir(self, path):
        path_components = self._path_dissect(path)
        try:
            self._find_path(self.inodes, path_components)
            raise DirectoryAlreadyExists(path)
        except TypeError:
            raise DirectoryAlreadyExists(path)
        except KeyError:
            self._find_path(self.inodes, path_components[:-1])[path_components[-1]] = {}

    def rmdir(self, path):
        pass

    def marshal(self):
        return pickle.dumps(self, -1)

    @staticmethod
    def unmarshal(string):
        return pickle.loads(string)

    def dir_or_inode(self, path):
        try:
            inode = self._find_path(self.inodes, self._path_dissect(path))
        except (KeyError, TypeError):
            #raise NoSuchPathExists(path)
            raise OSError(2, 'No such file or directory', path)
        return inode
