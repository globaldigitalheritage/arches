import sys
import os
import subprocess
import shutil
import urllib.request, urllib.error, urllib.parse
import zipfile
import datetime
import platform
import tarfile
from arches import settings

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here)


def install():
    if confirm_system_requirements():
        install_dir = os.path.join(site_packages_dir(), 'arches', 'install')
        django_install_location = os.path.join(site_packages_dir(), 'django')

        # INSTALL DJANGO, RAWES, SPHINX AND OTHER DEPENDENCIES
        tmpinstalldir = os.path.join(site_packages_dir(), 'arches', 'tmp')
        os.system("pip install -b %s setuptools --upgrade" % (tmpinstalldir))
        os.system("pip install -b %s -r %s" % (tmpinstalldir, os.path.join(install_dir, 'requirements.txt')))
        if settings.MODE == 'DEV':
            os.system("pip install -b %s -r %s" % (tmpinstalldir, os.path.join(install_dir, 'requirements_dev.txt')))
        shutil.rmtree(tmpinstalldir, True)


def site_packages_dir():
    if sys.platform == 'win32':
        return os.path.join(sys.prefix, 'Lib', 'site-packages')
    else:
        py_version = 'python%s.%s' % (sys.version_info[0], sys.version_info[1])
        return os.path.join(sys.prefix, 'lib', py_version, 'site-packages')

def confirm_system_requirements():  
    # CHECK PYTHON VERSION 
    if not sys.version_info >= (3, 7):   
        print('ERROR: Arches requires at least Python 3.7')  
        sys.exit(101) 
    else: 
        pass  

    return True

def activate_env(path_to_virtual_env):
    # ACIVATE THE VIRTUAL ENV
    if sys.platform == 'win32':
        activate_this = os.path.join(path_to_virtual_env, 'Scripts', 'activate_this.py')
    else:
        activate_this = os.path.join(path_to_virtual_env, 'bin', 'activate_this.py')
    execfile(activate_this, dict(__file__=activate_this))


def unzip_file(file_name, unzip_location):
    try:
        # first assume you have a .tar.gz file
        tar = tarfile.open(file_name, "r:gz")
        tar.extractall(path=unzip_location)
        tar.close()
    except:
        # next assume you have a .zip file
        with zipfile.ZipFile(file_name, 'r') as myzip:
            myzip.extractall(unzip_location)


def get_version(version=None):
    "Returns a PEP 440-compliant version number from VERSION."
    version = get_complete_version(version)

    # Now build the two parts of the version number:
    # major = X.Y[.Z]
    # sub = .devN - for pre-alpha releases
    #     | {a|b|rc}N - for alpha, beta and rc releases

    major = get_major_version(version)

    sub = ''
    if version[3] == 'alpha' and version[4] == 0:
        changeset = get_changeset()
        if changeset:
            sub = '.dev%s' % changeset

    elif version[3] != 'final':
        mapping = {'alpha': 'a', 'beta': 'b', 'rc': 'rc'}
        sub = mapping[version[3]] + str(version[4])

    return str(major + sub)


def get_major_version(version=None):
    "Returns major version from VERSION."
    version = get_complete_version(version)
    parts = 2 if version[2] == 0 else 3
    major = '.'.join(str(x) for x in version[:parts])
    return major


def get_complete_version(version=None):
    """Returns a tuple of the django version. If version argument is non-empty,
    then checks for correctness of the tuple provided.
    """
    if version is None:
        from arches import VERSION as version
    else:
        assert len(version) == 5
        assert version[3] in ('alpha', 'beta', 'rc', 'final')

    return version

def get_changeset(path_to_file=None):
    import os
    import subprocess
    from io import StringIO
    from management.commands.utils import write_to_file

    sb = StringIO()
    if not path_to_file:
        path_to_file =os.path.abspath(os.path.dirname(__file__))

    ver = ''
    try:
        hg_archival = open(os.path.abspath(os.path.join(here, '..', '.hg_archival.txt')),'r')
        the_file = hg_archival.readlines()
        hg_archival.close()
        node = ''
        latesttag = ''
        date = ''
        for line in the_file:
            if line.startswith('node:'):
                node = line.split(':')[1].strip()[:12]
            if line.startswith('latesttag:'):
                latesttag = line.split(':')[1].strip()
            if line.startswith('date:'):
                date = line.split(':')[1].strip()

        sb.writelines(['__VERSION__="%s"' % latesttag])
        sb.writelines(['\n__BUILD__="%s"' % node])
        ver = '%s:%s' % (latesttag, node)
        ver = date
        #write_to_file(os.path.join(path_to_file,'version.py'), sb.getvalue(), 'w')
    except:
        try:
            ver = subprocess.check_output(['hg', 'log', '-r', '.', '--template', '{latesttag}:{node|short}'])
            ver = subprocess.check_output(['hg', 'log', '-r', '.', '--template', '{node|short}'])
            ver = subprocess.check_output(['hg', 'log', '-r', '.', '--template', '{date}'])
            sb.writelines(['__VERSION__="%s"' % ver.split(':')[0]])
            sb.writelines(['\n__BUILD__="%s"' % ver.split(':')[1]])
            #write_to_file(os.path.join(path_to_file,'version.py'), sb.getvalue(), 'w')
        except:
            pass

    try:
        timestamp = datetime.datetime.utcfromtimestamp(float(ver))
    except ValueError:
        return None
    return timestamp.strftime('%Y%m%d%H%M%S')

if __name__ == "__main__":
    install()
