import fcntl, sys, stat, os, shutil
from errno import *
# from config import BLOCK_SIZE, CACHE_DIR
from sets import Set
from cache import LRUCache

import errno

BLOCK_SIZE = 1024 * 1024  # 1M
CACHE_DIR = '/var/cache/snfs'
CACHE_CAPACITY = 100 * 1024 * 1024

try:
    import _find_fuse_parts
except ImportError:
    pass
import fuse
from fuse import Fuse
from structures.inode import Inode, Tree
from api.functions import splitFile, upload_to_vk, download_from_vk, upload_main_inode
import time
from structures.exceptions import *

a = Inode(size=555211, blocks={1: range(11200, 11210), 2: range(11200, 11210), 3: range(11200, 11210)})
b = Inode(size=110001, blocks={1: range(11200, 11210), 2: range(11200, 11210), 3: range(11200, 11210)})
c = Inode(size=4451, blocks={1: range(11200, 11210), 2: range(11200, 11210), 3: range(11200, 11210)})

# Tree test
tree = Tree()

tree.mkdir('/home')
tree.mkdir('/home/horn')
tree.mkdir('/home/test')
tree.mkdir('/dom')
tree.mkdir('/home/test/dir1')

tree.inodes['/']['home']['test'].update({'1.jpg': a})
tree.inodes['/']['home'].update({'2.jpg': b})
tree.inodes['/']['home'].update({'3.jpg': c})

if not hasattr(fuse, '__version__'):
    raise RuntimeError, \
        "your fuse-py doesn't know of fuse.__version__, probably it's too old."

fuse.fuse_python_api = (0, 2)
fuse.feature_assert('stateful_files', 'has_init')


def flag2mode(flags):
    md = {os.O_RDONLY: 'r', os.O_WRONLY: 'w', os.O_RDWR: 'w+'}
    m = md[flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)]

    if flags | os.O_APPEND:
        m = m.replace('w', 'a', 1)

    return m


class Stat(fuse.Stat):
    # TODO: Implement handling of owners
    def __init__(self, inode=None):
        if inode:
            self.st_mode = stat.S_IFREG | 0644
            self.st_ino = inode.id
            self.st_dev = 0
            self.st_nlink = 1
            self.st_uid = os.getuid()
            self.st_gid = os.getgid()
            self.st_size = inode.size
            self.st_atime = int(time.time())
            self.st_mtime = inode.m_time
            self.st_ctime = self.st_mtime
        else:
            self.st_mode = stat.S_IFDIR | 0755
            self.st_ino = 0
            self.st_dev = 0
            self.st_nlink = 1
            self.st_uid = os.getuid()
            self.st_gid = os.getgid()
            self.st_size = BLOCK_SIZE
            self.st_atime = int(time.time())
            self.st_mtime = self.st_atime
            self.st_ctime = self.st_atime


cache = LRUCache(capacity=CACHE_CAPACITY)


class SNfs(Fuse):
    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)
        self.root = '/'
        try:
            os.mkdir(CACHE_DIR)  # create cache dir
        except OSError:  # path already exists
            pass

        tree_str = download_from_vk(tree=True)
        self.tree = Tree.unmarshal(tree_str)
        # self.tree = tree

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
        except (TypeError, KeyError):
            raise OSError(2, 'No such file or directory', path)
        for k in t:
            yield fuse.Direntry(k)

    def unlink(self, path):
        pass

    # TODO: clear cache if necessary
    def rmdir(self, path):
        path_components = Tree._path_dissect(path)
        sub = self.tree.inodes
        for i in path_components[:-1]:
            sub = sub[i]
        del sub[path_components[-1]]
        try:
            shutil.rmtree(CACHE_DIR + path)
        except OSError:
            pass

    def symlink(self, path, path1):
        pass

    def rename(self, path, path1):
        path_components = Tree._path_dissect(path)
        new_name = path1.strip('/').split('/')[-1]
        sub = self.tree.inodes
        for i in path_components[:-1]:
            sub = sub[i]
        old = sub.pop(path_components[-1])
        self.tree._find_path(self.tree.inodes, path_components[:-1])[new_name] = old
        os.rename(CACHE_DIR + path, CACHE_DIR + path1)
        cache.set(old.id, (old.size, path1))

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
        except (TypeError, KeyError):
            raise OSError(2, 'No such file or directory', path)
        if isinstance(t, Inode):
            if 0 < len <= t.size:
                # Assuming that tree branch mirrors in cache dir
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
        self.tree.mkdir(path)
        # create branch in CACHE_DIR if not exists
        if not os.path.exists(CACHE_DIR + path):
            try:
                os.makedirs(CACHE_DIR + path)
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise

    def utime(self, path, times):
        d_or_f = self.tree.dir_or_inode(path)
        if isinstance(d_or_f, Inode):
            if times:
                d_or_f.a_time = times[0]
                d_or_f.m_time = times[1]

    def access(self, path, mode):
        path_components = Tree._path_dissect(path)
        try:
            Tree._find_path(self.tree.inodes, path_components)
        except (TypeError, KeyError):
            return -EACCES

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

        class SNStatVFS(fuse.StatVfs):
            def __init__(self):
                self.f_bsize = BLOCK_SIZE
                self.f_frsize = self.f_bsize
                self.f_blocks = sys.maxint
                # TODO: would be nice if we can display API requests limit left as f_bfree
                self.f_bfree = self.f_blocks
                self.f_files = self.f_blocks
                self.ffree = self.f_blocks

        return SNStatVFS()

    def fsinit(self):
        os.chdir(self.root)

    def fsdestroy(self):
        # clear CACHE_DIR
        folder = CACHE_DIR
        for the_file in os.listdir(folder):
            file_path = os.path.join(folder, the_file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(e)
        # upload the tree
        upload_main_inode(self.tree.marshal())

    class SNFile(object):

        def __init__(self, path, flags, *mode, **kwargs):
            """
                initialize file for a folder
                if no file with such name exists, then we have to create one.
                all files are stored in cache (/var/cache/snfs/...)
                after fsdestroy all cache should be removed (task pending)
            """
            try:
                self.tree = kwargs['tree']
            except KeyError:
                pass
            self.path = path
            self.mode = mode  # remember the state
            self.log_changes = []

            path_components = Tree._path_dissect(self.path)
            if not os.path.exists(CACHE_DIR + self.path):
                try:
                    finode = Tree._find_path(self.tree.inodes, path_components)
                    if finode.size > 0:
                        download_from_vk(blocks=finode.blocks[1], size=finode.size, fullpath=self.path)
                    else:
                        open(CACHE_DIR + self.path, 'a').close()
                    self.finode = finode
                    nodes_to_delete = cache.set(self.finode.id, (self.finode.size, self.path))
                    for p in nodes_to_delete:
                        try:
                            os.remove(CACHE_DIR + p)
                        except OSError:
                            pass
                except (TypeError, KeyError):
                    if flag2mode(flags) in ['a', 'w+']:
                        finode = Inode(size=0, blocks={1: [], 2: [], 3: []})
                        Tree._find_path(self.tree.inodes, path_components[:-1])[path_components[-1]] = finode
                        open(CACHE_DIR + self.path, 'a').close()
                        self.finode = finode
                        nodes_to_delete = cache.set(self.finode.id, (self.finode.size, self.path))
                        for p in nodes_to_delete:
                            try:
                                os.remove(CACHE_DIR + p)
                            except OSError:
                                pass
                    else:
                        raise OSError(2, 'No such file or directory', path)
            else:
                self.finode = Tree._find_path(self.tree.inodes, path_components)
                try:
                    cache.get(self.finode.id)
                except KeyError:
                    pass

            self.file = os.fdopen(os.open(CACHE_DIR + path, flags, *mode),
                                  flag2mode(flags))
            self.fd = self.file.fileno()

        # in read() nothing to change as we've downloaded this file to the cache
        def read(self, length, offset):
            self.file.seek(offset)
            return self.file.read(length)

        def write(self, buf, offset):
            self.file.seek(offset)
            self.file.write(buf)
            # self.finode.size = len(buf)  # update size after every write operation
            s_block = offset / BLOCK_SIZE
            end_block = (len(buf) + offset) / BLOCK_SIZE
            self.log_changes.append((s_block, end_block))  # save to list all number of changed blocks

            return len(buf)

        def release(self, flags):
            # todo destroy object
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

            block_list = splitFile(CACHE_DIR + self.path)  # get list of blocks
            pos = self.file.tell()
            self.file.seek(0, 2)
            self.finode.size = self.file.tell()
            self.file.seek(pos, 0)  # return back to the current pos

            # the file already exists
            if len(self.log_changes) > 0:
                # (@WARNING: do not know how to deal with intersections)
                x, y = self.log_changes.pop()
                tmp = Set(range(x, y + 1))
                upd = len(self.log_changes)  # start uploading from the end
                block_order = []
                self.update_pending = []  # list to store blocks that need update
                for i in range(0, upd):
                    x, y = self.log_changes.pop()
                    t = Set(range(x, y + 1))
                    tmp = tmp | (t.difference(tmp))  # expand the set with t - tmp

                for i in tmp:
                    block_order.append(i)  # set --> list to perform order operation
                block_order.sort()  # sort block order
                for i in block_order:
                    if i < len(block_list):
                        self.update_pending.append(block_list[i])  # fill updated blocks to the array for uploading

                new_block_id_list = upload_to_vk(self.update_pending)  # upload updated blocks to the vk

                for i in block_order:
                    if i < len(
                            block_list):  # if once block had been updated before this part of file was cut -> do not upload
                        self.finode.blocks[1][i] = new_block_id_list[i]

            # the file has just been created with zero bytes length
            else:
                new_block_id_list = upload_to_vk(block_list)
                self.finode.blocks[1] = new_block_id_list

            path_components = Tree._path_dissect(self.path)
            Tree._find_path(self.tree.inodes, path_components[:-1])[path_components[-1]] = self.finode

        def flush(self):
            self._fflush()
            # cf. xmp_flush() in fusexmp_fh.c
            # block_list = splitFile(CACHE_DIR + self.path)  # get list of blocks

            # change inode size
            pos = self.file.tell()
            self.file.seek(0, 2)
            self.finode.size = self.file.tell()
            self.file.seek(pos, 0)  # return back to the current pos
            path_components = Tree._path_dissect(self.path)
            Tree._find_path(self.tree.inodes, path_components[:-1])[path_components[-1]] = self.finode
            # # the file already exists
            # if len(self.log_changes) > 0:
            #     # (@WARNING: do not know how to deal with intersections)
            #     x, y = self.log_changes.pop()
            #     tmp = Set(range(x, y + 1))
            #     upd = len(self.log_changes)  # start uploading from the end
            #     block_order = []
            #     self.update_pending = []  # list to store blocks that need update
            #     for i in range(0, upd):
            #         x, y = self.log_changes.pop()
            #         t = Set(range(x, y + 1))
            #         tmp = tmp | (t.difference(tmp))  # expand the set with t - tmp

            #     for i in tmp:
            #         block_order.append(i)  # set --> list to perform order operation
            #     block_order.sort()  # sort block order
            #     for i in block_order:
            #         if i < len(block_list):
            #             self.update_pending.append(block_list[i])  # fill updated blocks to the array for uploading

            #     new_block_id_list = upload_to_vk(self.update_pending)  # upload updated blocks to the vk

            #     for i in block_order:
            #         if i < len(block_list):  # if once block had been updated before this part of file was cut -> do not upload
            #             self.finode.blocks[1][i] = new_block_id_list[i]

            # # the file has just been created with zero bytes length
            # else:
            #     new_block_id_list = upload_to_vk(block_list)
            #     self.finode.blocks[1] = new_block_id_list

            os.close(os.dup(self.fd))

        def fgetattr(self):
            return os.fstat(self.fd)

        def ftruncate(self, len):
            self.file.truncate(len)
            c = len(tree.inode.size)  # how much blocks did we have

            bl_id = len / self.data_only + 1  # how much blocks we will have now

            for i in range(1, c - bl_id):  # delete block links
                snfs.tree.inode.blocks.pop(bl_id)  # not tested. may be bl_id + 1

            self.snfs.tree.inode.size = os.path.getsize(CACHE_DIR + self.path)  # update size in the inode

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
        self.SNFile.tree = self.tree
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


# comments (in case smth bad happens)
# in def __init__ (class SNfile)
# inode = snfs.tree.dir_or_inode(path)
# if isinstance(inode, Inode):
#    self.isnewfile = False                  ## API function MUST be implemented. Download file to the entered path.
## Then open it as a simple file
#    download_from_vk(SNfs.tree.dir_or_inode(path).blocks,
#                     CACHE_DIR + path, inode.size)

# else: # create new inode in directory
#    self.isnewfile = True
