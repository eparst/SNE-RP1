import os, sys
from errno import *
import stat
import fcntl

try:
    import _find_fuse_parts
except ImportError:
    pass
import fuse
from fuse import Fuse
from structures.inode import Inode, Tree
import time
from utils.exceptions import *

if not hasattr(fuse, '__version__'):
    raise RuntimeError, \
        "your fuse-py doesn't know of fuse.__version__, probably it's too old."

fuse.fuse_python_api = (0, 2)

fuse.feature_assert('stateful_files', 'has_init')

BLOCK_SIZE = 1024 * 1024  # 1M
CACHE_DIR = '/var/cache/snfs/.cache'


def flag2mode(flags):
    md = {os.O_RDONLY: 'r', os.O_WRONLY: 'w', os.O_RDWR: 'w+'}
    m = md[flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)]

    if flags | os.O_APPEND:
        m = m.replace('w', 'a', 1)

    return m


# stub
TREE = Tree()


class Stat(fuse.Stat):
    def __init__(self, inode=None):
        if inode:
            self.st_mode = 0644
            self.st_ino = inode.id
            self.st_dev = 0
            self.st_nlink = 1
            self.st_uid = os.getuid()
            self.st_gid = os.getgid()
            self.st_size = inode.size
            self.st_atime = int(time.time())
            self.st_mtime = time.mktime(inode.last_modified.timetuple())
            self.st_ctime = self.st_atime
        else:
            self.st_mode = stat.S_IFDIR | 0755
            self.st_ino = 0
            self.st_dev = 0
            self.st_nlink = 1
            self.st_uid = os.getuid()
            self.st_gid = os.getgid()
            self.st_size = 4096
            self.st_atime = int(time.time())
            self.st_mtime = self.st_atime
            self.st_ctime = self.st_atime


class SNfs(Fuse):
    def __init__(self, *args, **kw):

        Fuse.__init__(self, *args, **kw)

        self.root = '/'
        os.mkdir(CACHE_DIR)
        # TODO: download tree from SN and save to .cache directory. Stub for now
        self.tree = TREE

    def getattr(self, path):
        d_or_f = self.tree.dir_or_inode(path)
        if isinstance(d_or_f, Inode):
            stats = Stat(inode=d_or_f)
        else:
            stats = Stat()
        return stats

    def readlink(self, path):
        pass

    def readdir(self, path, offset):
        path_components = Tree._path_dissect(path)
        try:
            t = Tree._find_path(self.tree.inodes, path_components)
        except TypeError or KeyError:
            raise NoSuchPathExists(path)
        for k in t:
            yield k

    def unlink(self, path):
        pass

    # TODO: clear cache if necessary
    def rmdir(self, path):
        path_components = Tree._path_dissect(path)
        sub = self.tree.inodes
        for i in path_components[:-1]:
            sub = sub[i]
        del sub[path_components[-1]]

    def symlink(self, path, path1):
        pass

    def rename(self, path, path1):
        path_components = Tree._path_dissect(path)
        new_name = path1.strip('/').split('/')[-1]
        sub = self.tree.inodes
        for i in path_components[:-1]:
            sub = sub[i]
        old = sub.pop(path_components[-1])
        self._find_path(self.inodes, path_components[:-1])[new_name] = old

    def link(self, path, path1):
        pass

    def chmod(self, path, mode):
        pass

    def chown(self, path, user, group):
        pass

    def truncate(self, path, len):
        path_components = Tree._path_dissect(path)
        try:
            t = Tree._find_path(self.tree.inodes, path_components)
        except TypeError or KeyError:
            raise NoSuchPathExists(path)
        if isinstance(t, Inode):
            if 0 < len <= t.size:
                # Assuming that tree branch mirrors in .cache dir
                f = open(CACHE_DIR + path, "a")
                f.truncate(len)
                f.close()
                # clear respective blocks in Inode
                t.size = len
                blocks = t.size / BLOCK_SIZE
                if t.size % BLOCK_SIZE != 0:
                    blocks += 1
                t.blocks = t.blocks[:blocks]

    def mknod(self, path, mode, dev):
        pass

    def mkdir(self, path, mode):
        self.inodes.mkdir(path)

    def utime(self, path, times):
        d_or_f = self.tree.dir_or_inode(path)
        #if isinstance(d_or_f, Inode):
        #    d_or_f.
        os.utime("." + path, times)

    #    The following utimens method would do the same as the above utime method.
    #    We can't make it better though as the Python stdlib doesn't know of
    #    subsecond preciseness in acces/modify times.
    #
    #    def utimens(self, path, ts_acc, ts_mod):
    #      os.utime("." + path, (ts_acc.tv_sec, ts_mod.tv_sec))

    def access(self, path, mode):
        path_components = Tree._path_dissect(path)
        try:
            Tree._find_path(self.tree.inodes, path_components)
        except TypeError or KeyError:
            return -EACCES


        #    This is how we could add stub extended attribute handlers...
        #    (We can't have ones which aptly delegate requests to the underlying fs
        #    because Python lacks a standard xattr interface.)
        #
        #    def getxattr(self, path, name, size):
        #        val = name.swapcase() + '@' + path
        #        if size == 0:
        #            # We are asked for size of the value.
        #            return len(val)
        #        return val
        #
        #    def listxattr(self, path, size):
        #        # We use the "user" namespace to please XFS utils
        #        aa = ["user." + a for a in ("foo", "bar")]
        #        if size == 0:
        #            # We are asked for size of the attr list, ie. joint size of attrs
        #            # plus null separators.
        #            return len("".join(aa)) + len(aa)
        #        return aa

    def statfs(self):
        """
        Should return an object with statvfs attributes (f_bsize, f_frsize...).
        Eg., the return value of os.statvfs() is such a thing (since py 2.2).
        If you are not reusing an existing statvfs object, start with
        fuse.StatVFS(), and define the attributes.

        To provide usable information (ie., you want sensible df(1)
        output, you are suggested to specify the following attributes:

            - f_bsize - preferred size of file blocks, in bytes
            - f_frsize - fundamental size of file blcoks, in bytes
                [if you have no idea, use the same as blocksize]
            - f_blocks - total number of blocks in the filesystem
            - f_bfree - number of free blocks
            - f_files - total number of file inodes
            - f_ffree - nunber of free file inodes
        """

        return os.statvfs(".")

    def fsinit(self):
        os.chdir(self.root)

    # TODO: Upload tree on unmount
    def fsdestroy(self):
        pass

    class SNFile(object):

        def __init__(self, path, flags, *mode):
            # self.file = os.fdopen(os.open("." + path, flags, *mode),
            #                      flag2mode(flags))
            # self.fd = self.file.fileno()

            # call to API to download all the associated file blocks
            s = '\x0a\x0b\x0c\x0d'
            # write to cache dir
            f = open('.cache')

        def read(self, length, offset):
            self.file.seek(offset)
            return self.file.read(length)

        def write(self, buf, offset):
            self.file.seek(offset)
            self.file.write(buf)
            return len(buf)

        def release(self, flags):
            self.file.close()

        def _fflush(self):
            if 'w' in self.file.mode or 'a' in self.file.mode:
                self.file.flush()

        def fsync(self, isfsyncfile):
            self._fflush()
            if isfsyncfile and hasattr(os, 'fdatasync'):
                os.fdatasync(self.fd)
            else:
                os.fsync(self.fd)

        def flush(self):
            self._fflush()
            # cf. xmp_flush() in fusexmp_fh.c
            os.close(os.dup(self.fd))

        def fgetattr(self):
            return os.fstat(self.fd)

        def ftruncate(self, len):
            self.file.truncate(len)

        def lock(self, cmd, owner, **kw):
            # The code here is much rather just a demonstration of the locking
            # API than something which actually was seen to be useful.

            # Advisory file locking is pretty messy in Unix, and the Python
            # interface to this doesn't make it better.
            # We can't do fcntl(2)/F_GETLK from Python in a platfrom independent
            # way. The following implementation *might* work under Linux. 
            #
            # if cmd == fcntl.F_GETLK:
            #     import struct
            # 
            #     lockdata = struct.pack('hhQQi', kw['l_type'], os.SEEK_SET,
            #                            kw['l_start'], kw['l_len'], kw['l_pid'])
            #     ld2 = fcntl.fcntl(self.fd, fcntl.F_GETLK, lockdata)
            #     flockfields = ('l_type', 'l_whence', 'l_start', 'l_len', 'l_pid')
            #     uld2 = struct.unpack('hhQQi', ld2)
            #     res = {}
            #     for i in xrange(len(uld2)):
            #          res[flockfields[i]] = uld2[i]
            #  
            #     return fuse.Flock(**res)

            # Convert fcntl-ish lock parameters to Python's weird
            # lockf(3)/flock(2) medley locking API...
            op = {fcntl.F_UNLCK: fcntl.LOCK_UN,
                  fcntl.F_RDLCK: fcntl.LOCK_SH,
                  fcntl.F_WRLCK: fcntl.LOCK_EX}[kw['l_type']]
            if cmd == fcntl.F_GETLK:
                return -EOPNOTSUPP
            elif cmd == fcntl.F_SETLK:
                if op != fcntl.LOCK_UN:
                    op |= fcntl.LOCK_NB
            elif cmd == fcntl.F_SETLKW:
                pass
            else:
                return -EINVAL

            fcntl.lockf(self.fd, op, kw['l_start'], kw['l_len'])

    def main(self, *a, **kw):

        self.file_class = self.SNFile

        return Fuse.main(self, *a, **kw)


def main():
    usage = """
Userspace nullfs-alike: mirror the filesystem tree from some point on.

""" + Fuse.fusage

    server = SNfs(version="%prog " + fuse.__version__,
                  usage=usage,
                  dash_s_do='setsingle')

    server.parser.add_option(mountopt="root", metavar="PATH", default='/',
                             help="mirror filesystem from under PATH [default: %default]")
    server.parse(values=server, errex=1)

    try:
        if server.fuse_args.mount_expected():
            os.chdir(server.root)
    except OSError:
        print >> sys.stderr, "can't enter root of underlying filesystem"
        sys.exit(1)

    server.main()


if __name__ == '__main__':
    main()
