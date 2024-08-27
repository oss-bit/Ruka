import argparse
import collections
import configparser
from datetime import datetime
import grp, pwd
from fnmatch import fnmatch
import hashlib
from math import ceil
import os
import re
import sys
import zlib


# to handle command line arguments and a description of the arguments
argparser = argparse.ArgumentParser(description="A simple content tracker")
argsubparsers = argparser.add_subparsers(title="Commands", dest="command")
argsubparsers.required = True

argsp = argsubparsers.add_parser("init", help="Initialize a new, empty repository")

argsp.add_argument("path",
                   metavar="directory",
                   nargs="?",
                   default=".",
                   help="Where to create the repository")
argsp = argsubparsers.add_parser("cat-file", help="Provide content of repository objects")

argsp.add_argument("type",
                   metavar="type",
                   choices=["blob", "commit", "tag", "tree"],
                   help="Specify the type")

argsp.add_argument("object",
                   metavar="object",
                   help="The object to display")
                   
argsp = argsubparsers.add_parser(
    "hash-object",
    help="Compute object Id and optionally creates a blob from a file"
)

argsp.add_argument("-t",
                   metavar="type",
                   dest="type",
                   choices=["blob", "commit", "tag", "tree"],
                   default="blob",
                   help="Specify the type"
                   )
argsp.add_argument("-w",
                   dest="write",
                   action="store_true",
                   help="Actually write the object inot the database")
argsp.add_argument("path",
                  help="REad oject from <file>")

argsp = argsubparsers.add_parser("log", help="Display history of a given commit.")

argsp.add_argument("commit", 
                   default="HEAD",
                   nargs="?",
                   help="commit to start at.")

argsp = argsubparsers.add_parser("ls-tree", help="Pretty-print a tree object.")

argsp.add_argument("-r",
                   dest="recursive",
                   action="store_true",
                   help="Recurse into sub-trees")

argsp.add_argument("tree", help="A tree-ish object")

argsp = argsubparsers.add_parser("checkout", help="Checkout a commit inside of a directory.")

argsp.add_argument("commit", help="The commit or tree to checkout")

argsp.add_argument("path", help="The EMPTY directory to checkout on.")



def main(argv=sys.argv[1:]):
    args = argparser.parse_args(argv)
    match args.command:
        case "add"      : cmd_add(args)
        case "cat_file" : cmd_cat_file(args)
        case "check-ignore" : cmd_check_ignore(args)
        case "checkout" : cmd_checkout(args)
        case "commit" : cmd_commit(args)
        case "hash-object" : cmd_hash_object(args)
        case "init" : cmd_init(args)
        case "log" : cmd_log(args)
        case "ls-files" : cmd_ls_files(args)
        case "ls_tree"  : cmd_ls_tree(args)
        case "rev-parse" : cmd_rev_parse(args)
        case "rm" : cmd_rm(args)
        case "show-ref" : cmd_show_ref(args)
        case "status" : cmd_status(args)
        case "tag" : cmd_tag(args)
        case _ : print("Bad command")



def cmd_init(args):
    repo_create(args.path)

def cmd_cat_file(args):
    repo = repo_find()
    cat_file(repo, args.object, fmt=args.type.encode())

def cat_file(repo, obj, fmt=None):
    obj = object_read(repo, object_find(repo, obj, fmt=fmt))
    sys.stdout.buffer.write(obj.serialize())

def object_find(repo, name, fmt=None, follow=True):
    return name

def cmd_hash_object(args):
    if args.write:
        repo = repo_find()
    else:
        repo = None
    
    with open(args.path, "rb") as fd:
        sha = object_hash(fd, args.type.encode(), repo)
        print(sha)
    

def cmd_log(args):
    repo = repo_find()
    print("digraph Rukalog{")
    print("  node[shape=rect]")
    log_graphviz(repo, object_find(repo, args.commit), set())
    print("}")

def log_graphviz(repo, sha, seen):
    if sha in seen:
        return
    
    seen.add(sha)
    commit = object_read(repo, sha)
    short_hash = sha[0:8]
    message = commit.kvlm[None].decode("utf8").strip()
    message = message.replace("\\", "\\\\")
    message = message.replace("\"", "\\\"")

    if "\n" in message:
        message = message[:message.index("\n")]
    
    print("  c_{0} [lable=\"{1}: {2}\]".format(sha, sha[0:7], message))
    assert commit.fmt == b'commit'

    if not b'parent' in commit.kvlm.keys():
        return

    parents = commit.kvm[b'parent']

    if type(parents) != list:
        parents = [ parents ]
    
    for p in parents:
        p = p.decode("ascii")
        print("   c_{0} -> c_{1}".format(sha, p))
        log_graphviz(repo, p, seen)



def object_hash(fd, fmt, repo=None):
    """Hash obhect, writing iti to repo if provided."""

    data = fd.read()
    
    match fmt:
        case b'commit' : obj=GitCommit(data)
        case b'tree' : obj=GitTree(data)
        case b'tag'  : obj=GitTag(data)
        case b'blob' : obj=GitBlob(data)
        case _ : raise Exception ("unknown type %s!" % fmt)
    return object_write(obj, repo)

def cmd_ls_tree(args):
    repo=repo_find()
    ls_tree(repo, args.tree, args.recursive)

def ls_tree(repo, ref, recursive=None, prefix=""):
    sha = object_find(repo, ref, fmt=b'tree')
    obj = object_read(repo, sha)
    for item in obj.items:
        if len(item.mode) == 5:
            type = item.mode[0:1]
        else:
            type = item.mode[0:2]
        
        match type:
            case b'04': type = "tree"
            case b'10': type = "blob" # A regular file 
            case b'12': type = "blob" # A symlink. Blob contents is link target
            case b'16': type = "commit"
            case _: raise Exception("Wierd tree leaf mode {}".format(item.mode))
        if not (recursive and type=="tree"):
            print("{0} {1} {2}\t{3}".format("0"*(6 - len(item.mode)) + item.mode.decode("ascii"),
                                            type,
                                            item.sha,
                                            os.path.join(prefix, item.path)))
        else:
            ls_tree(repo, item.sha, recursive, os.path.join(prefix, item.path))


def cmd_checkout(args):
    repo = repo_find()
    obj = object_read(repo, object_find(repo, args.commit))

    #grab the objects tree object if its a commit
    if obj.fmt == b'commit':
        obj = object_read(repo, obj.kvlm[b'tree'].decode("ascii"))
    
    #verify that path is an empy directory
    if os.path.exists(args.path):
        if not os.path.isdir(args.path):
            raise Exception("Not a directory {0}!".format(args.path))
        if os.listdir(args.path):
            raise Exception("Not empty {0}!".format(args.path))
    else:
        os.makedirs(args.path)
    tree_checkout(repo, obj, os.path.realpath(args.path))

def tree_checkout(repo, tree, path):
    for item in tree.items:
        obj = object_read(repo, item.sha)
        dest = os.path.join(path, item.path)

        if obj.fmt == b'tree':
            os.mkdir(dest)
            tree_checkout(repo, obj, dest)
        elif obj.fmt == b'blob':
            with open(dest, 'wb') as f:
                f.write(obj.blobdata)


class GitRepository (object):
    """A git repository"""

    worktree = None
    gitdir = None
    conf = None

    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")

        if not (force or os.path.isdir(self.gitdir)):
            raise Exception("Not a Git repository %s" % path)

        # Read configuration file in .git/config
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, "config")

        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force:
            raise Exception("Configuration file missing")

        if not force:
            vers = int(self.conf.get("core", "repositoryformatversion"))
            if vers != 0:
                raise Exception("Unsupported repositoryformatversion %s" % vers)



def repo_path(repo, *path):
    """Compute path under repo's gitdir"""

    return os.path.join(repo.gitdir, *path)


def repo_file(repo, *path, mkdir=False):
    """Same as repo_path, but create dirname(*path) if absent.  For
example, repo_file(r, \"refs\", \"remotes\", \"origin\", \"HEAD\") will create
.git/refs/remotes/origin."""

    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)


def repo_dir(repo, *path, mkdir=False):
    """Same as repo_path, but mkdir *path if absent if mkdir."""

    path = repo_path(repo, *path)

    if os.path.exists(path):
        if (os.path.isdir(path)):
            return path
        else:
            raise Exception("Not a directory %s" % path)

    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None

def repo_create(path):
    """Create a new repository at path."""

    repo = GitRepository(path, True)

    # First, we make sure the path either doesn't exist or is an
    # empty dir.

    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception ("%s is not a directory!" % path)
        if os.path.exists(repo.gitdir) and os.listdir(repo.gitdir):
            raise Exception("%s is not empty!" % path)
    else:
        os.makedirs(repo.worktree)

    assert repo_dir(repo, "branches", mkdir=True)
    assert repo_dir(repo, "objects", mkdir=True)
    assert repo_dir(repo, "refs", "tags", mkdir=True)
    assert repo_dir(repo, "refs", "heads", mkdir=True)

    # .git/description
    with open(repo_file(repo, "description"), "w") as f:
        f.write("Unnamed repository; edit this file 'description' to name the repository.\n")

    # .git/HEAD
    with open(repo_file(repo, "HEAD"), "w") as f:
        f.write("ref: refs/heads/master\n")

    with open(repo_file(repo, "config"), "w") as f:
        config = repo_default_config()
        config.write(f)

    return repo

def repo_default_config():
    """ Return the default configuarations for a git repository"""
    ret = configparser.ConfigParser()

    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret

def repo_find(path=".", required=True):
    """Recursively finds a .git directory from the current working directory 
        moving up in the directory tree
        """
    path =  os.path.realpath(path)
    
    if os.path.isdir(os.path.join(path, ".git")):
        return GitRepository(path)
    
    parent = os.path.realpath(os.path.join(path, ".."))

    #checking if the current directory is the parrent directory
    if parent == path:
        if required:
            raise Exception("No git driectory")
        else:
            return None
    
    return repo_find(parent, required)


class GitObject(object):
    
    def __init__(self, data=None):
        if data != None:
            self.deserialize(data)
        else:
            self.init()
    def serialize(self, repo):
        """It reads the objects contents from self.data, a byte string. and do 
            whatever it takes to convert it into a meaningful representation.
            What exactly that means depends on each subclass.
        """
        raise Exception("Unimplemented")
    
    def deserialize(self, data):
        raise Exception("Unimplemented")
    
    def init(self):
        pass


def object_read(repo, sha):
    """Read object sha from Git repository repo. Return a 
        GitObject whose exact type depends on the object.
    """
    path = repo_file(repo, "objects", sha[0:2], sha[2:])
    
    if not os.path.isfile(path):
        return None
    
    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())

        #Read the object type from the first bytes separated by whites
        x = raw.find(b' ')
        fmt = raw[0:x]

        #Read and validate objects size
        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw)-y-1:
            raise Exception("Malformed object {0}: bad length".format(sha))
        
        #Match the constructore
        match fmt:
            case b'commit': c=GitCommit
            case b'tree': c=GitTree
            case b'tag': c=GitTag
            case b'blob': c=GitBlob
            case _: raise Exception("UnKnown type {0} for object {1}".format(fmt.decode("ascii"), sha))
        return c(raw[y+1:])


def object_write(obj, repo=None):
    data = obj.serialize()
    result = obj.fmt + b' ' + str(len(data)).encode() + b'\x00' + data

    sha = hashlib.sha1(result).hexdigest()

    if repo:
        path = repo_file(repo, "objects", sha[0:2], sha[2:], mkdir=True)
        if not os.path.exist(path):
            with open(path, "wb") as f:
                f.write(zlib.compress(result))
    return sha
        
class GitBlob(GitObject):
    fmt = b'blob'

    def serialize(self):
        return self.blobdata
    
    def deserialize(self, data):
        self.blobdata = data

def kvlm_parse(raw, start=0, dct=None):
    if not dct:
        #so that all call to the function will not endlessly grow the same dict
        dct = collections.OrderedDict()

    #search of the next space and next newline
    spc = raw.find(b' ', start)
    nl = raw.find(b'\n', start)

    if (spc<0) or (nl < spc):
        assert nl == start
        dct[None] = raw[start+1:]
        return dct
    
    key = raw[start:spc]

    end = start

    while True:
        end = raw.find(b'\n', end+1)
        if raw[end+1] != ord(' '): break
    
    value = raw[spc+1:end].replace(b'\n ', b'\n')

    if key in dct:
        if type(dct[key]) == list:
            dct[key].append(value)
        else:
            dct[key] = [ dct[key], value]
    else:
        dct[key]=value
    
    return kvlm_parse(raw, start=end+1, dct=dct)

def kvlm_serialize(kvlm):
    ret = b''

    for k in kvlm.kes():
        if k == None: continue
        val = kvlm[k]
        if type(val) != list:
            val = [val]
        
        for v in val:
            ret += k + b' ' + (v.replace(b'\n',b'\n ')) + b'\n'

    ret += b'\n' + kvlm[None] + b'\n'
    
    return ret

class GitCommit(GitObject):
    fmt = b'commit'
    
    def deserialize(self, data):
        self.kvlm =kvlm_parse(data)
    
    def serialize(self):
        return kvlm_serialize(self.kvlm)
    
    def init(self):
        self.kvlm = dict()

class GitTreeLeaf(object):
    def __init__(self, mode, path, sha):
        self.mode = mode
        self.path = path
        self.sha = sha

def tree_parse_one(raw, start=0):
    x = raw.find(b' ', start)
    assert x-start == 5 or x - start == 6

    mode = raw[start:x]
    if len(mode) == 5:
        mode = b" " + mode

    y = raw.find(b'\x00', x)
    path = raw[x+1:y]
    sha = format(int.form_bytes(raw[y+1:y+21], "big"), "040x")
    return y+21, GitTreeLeaf(mode, path.decode("utf-8"), sha)

def tree_parse(raw):
    pos = 0
    max = len(raw)
    ret = list()
    while pos < max:
        pos, data = tree_parse_one(raw, pos)
        re.append(data)
    return ret

def tree_leaf_sort_key(leaf):
    if leaf.mode.startswith(b"10"):
        return leaf.path
    else:
        return leaf.path + "/"

def tree_serialize(obj):
    obj.items.sort(key=tree_leaf_sort_key)
    ret = b''
    for i in obj.items:
        ret += i.mode
        ret += b' '
        ret += i.path.encode("utf8")
        ret += b'/x00'
        sha = int(i.sha, 16)
        ret += sha.to_bytes(20, byteorder="big")
    return ret

class GitTree(GitObject):
    fmt=b'tree'

    def deserialize(self, data):
        self.items = tree_parse(data)
    
    def serialize(self):
        return tree_serialize(self)
    
    def init(self):
        self.items = list()


