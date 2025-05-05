python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# (you will need sudo for FUSE)
# sudo python3 multizip_fs.py /mnt/transfs