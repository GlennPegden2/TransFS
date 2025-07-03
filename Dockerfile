FROM python:3.10-slim


RUN apt-get update
RUN apt-get install -y fuse3 samba wget unzip libguestfs-tools p7zip

# Not needed for production, but useful for testing
RUN pip install pytest 
RUN pip install debugpy 

COPY requirements.txt .
RUN pip install -r requirements.txt

# Add FUSE permission
RUN mkdir /mnt/transfs && chmod 755 /mnt/transfs

# Allow FUSE mount
RUN echo 'user_allow_other' >> /etc/fuse.conf

# Add a basic Samba config
COPY smb.conf /etc/samba/smb.conf

# Set up a Samba user (default user: smbuser, password: smbpass)
RUN useradd -M -s /sbin/nologin smbuser && \
    (echo "smbpass"; echo "smbpass") | smbpasswd -s -a smbuser

# Expose the default SMB port
EXPOSE 445
EXPOSE 80

WORKDIR /app
#COPY ./app /app

# Start Samba and the FUSE filesystem
CMD service smbd start && python3 -m transfs && tail -f /dev/null