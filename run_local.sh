#!/bin/bash
[ "$EUID" -ne 0 ] && echo "Please run as root (try using sudo)." && exit 1

python3 -m venv venv
source ./venv/bin/activate
pip install --upgrade pip
pip install -q -r requirements.txt
pip install -q tenacity --upgrade # Fix Mega.nz issue on Python3.10+

# (you will need sudo for FUSE)
# sudo python3 multizip_fs.py /mnt/transfs

# Add user_allow_other to fuse.conf
echo 'user_allow_other' | sudo tee -a /etc/fuse.conf

# Create mount points with proper permissions
sudo mkdir -p /mnt/transfs /mnt/filestorefs
sudo chmod 777 /mnt/transfs /mnt/filestorefs

[ ! -f /etc/samba/smb.conf.bak ] && {
[ -f /etc/samba/smb.conf ] && cp /etc/samba/smb.conf /etc/samba/smb.conf.transfs_bak
cp ./smb.conf /etc/samba/smb.conf
}

cd app
service smbd start &&

echo "IP: $(hostname -I | awk '{print $1}'), FQDN: $(hostname -f)"

python3 transfs.py 2>&1 | tee /tmp/transfs.log &

uvicorn main:app --host 0.0.0.0 --port 8000 --reload &&
tail -f /dev/null