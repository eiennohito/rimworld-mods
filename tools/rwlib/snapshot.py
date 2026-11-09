"""Independent file snapshots, sharing extents when the filesystem supports it."""
import errno
import fcntl
import shutil


# Linux FICLONE: writes to either inode subsequently use copy-on-write.
FICLONE = 0x40049409
UNSUPPORTED = {errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTTY, errno.EINVAL, errno.ENOSYS}


def copy_file(source, destination):
    """Copy to a new file; fall back only when reflinks are unsupported."""
    with open(source, 'rb') as incoming, open(destination, 'xb') as outgoing:
        try:
            fcntl.ioctl(outgoing.fileno(), FICLONE, incoming.fileno())
        except OSError as error:
            if error.errno not in UNSUPPORTED:
                raise
            shutil.copyfileobj(incoming, outgoing)
    shutil.copystat(source, destination)
    return destination


def copy_tree(source, destination, **kwargs):
    return shutil.copytree(source, destination, copy_function=copy_file, **kwargs)
