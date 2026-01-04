#!/bin/bash

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Copyright 2018-2019 Alessandro "Locutus73" Miele

# You can download the latest version of this script from:
# https://github.com/MiSTer-devel/CIFS_MiSTer

# Forked By Glenn Pegden to support multiple maps (to test TransFS Docker)
# Version 2.1.0 - 2022-04-16 - Introduced "SHARE_DIRECTORY" option; useful if you don't have a dedicated MiSTer-share on the remote server, but only a specific folder which should be mounted here.
# Version 2.0.1 - 2019-05-06 - Removed kernel modules downloading, now the script asks to update the MiSTer Linux system when necessary.
# Version 2.0 - 2019-02-05 - Renamed from mount_cifs.sh and umount_cifs.sh to cifs_mount.sh and cifs_umount.sh for having them sequentially listed in alphabetical order.
# Version 1.8 - 2019-02-03 - Added MOUNT_AT_BOOT option: "true" for automounting CIFS shares at boot time; it will create start/kill scripts in /etc/network/if-up.d and /etc/network/if-down.d.
# Version 1.7 - 2019-02-02 - The script temporarily modifies the firewalling rules for querying the CIFS Server name with NetBIOS when needed.
# Version 1.6 - 2019-02-02 - The script tries to download kernel modules (when needed) using SSL certificate verification.
# Version 1.5.1 - 2019-01-19 - Now the script checks if kernel modules are built in, so it's compatible with latest MiSTer Linux distros.
# Version 1.5 - 2019-01-15 - Added WAIT_FOR_SERVER option; set it to "true" in order to wait for the CIFS server to be reachable; useful when using this script at boot time.
# Version 1.4 - 2019-01-07 - Added support for an ini configuration file with the same name as the original script, i.e. mount_cifs.ini; changed LOCAL_DIR="*" behaviour so that, when SINGLE_CIFS_CONNECTION="true", all remote directories are listed and mounted locally; kernel modules moved to /media/fat/linux.
# Version 1.3 - 2019-01-05 - Added an advanced SINGLE_CIFS_CONNECTION option for making a single CIFS connection to the CIFS server, you can leave it set to "true"; implemented LOCAL_DIR="*" for mounting all local directories on the SD root.
# Version 1.2 - 2019-01-04 - Changed the internal field separator from space " " to pipe "|" in order to allow directory names with spaces; made the script verbose with some output.
# Version 1.1.1 - 2019-01-03 - Improved server name resolution speed for multiple mount points; now you can directly use an IP address; added des_generic.ko fscache.ko kernel modules.
# Version 1.1 - 2019-01-03 - Implemented multiple mount points, improved descriptions for user options.
# Version 1.0.1 - 2018-12-22 - Changed some option descriptions, thanks NML32
# Version 1.0 - 2018-12-20 - First commit



#=========   USER OPTIONS   =========
#You can edit these user options or make an ini file with the same
#name as the script, i.e. mount_cifs.ini, containing the same options.

# Menu timeout in seconds (0 to disable auto-selection)
MENU_TIMEOUT=5

# Default share selection (1-based index, 0 to disable default)
DEFAULT_SELECTION=1


#=========   SHARE DEFINITIONS   =========
# Define multiple share configurations below
# Format: SERVER|PORT|SHARE|SHARE_DIRECTORY|USERNAME|PASSWORD|DOMAIN|DESCRIPTION
# PORT: 445 for standard SMB, or custom port (e.g., 3445)
# Leave SHARE_DIRECTORY blank if mounting share root
# Leave USERNAME/PASSWORD blank for guest access
# Pipe characters | within values are not supported

declare -a SHARE_CONFIGS=(
    # Pi linked to external HD full of retro software
    "retropie|445|mister||pi|raspberry||RetroPie Share"

	#TransFS Docker Testbed
    "GLENNS-DESKTOP|3445|TransFS|MiSTer|root|1||TransFS Docker (Port 3445)"

	#NAS (not in Mister Format, but has loads of software)
    "NAS|3445|software||nas|f1rk1n#nas||NAS Software Share"

)

# Legacy options - populated from menu selection
SERVER=""
PORT=""
SHARE=""
SHARE_DIRECTORY=""
USERNAME=""
PASSWORD=""
DOMAIN=""

#Local directory/directories where the share will be mounted.
#- It can ba a single directory, i.e. "cifs", so the remote share, i.e. \\NAS\MiSTer
#  will be directly mounted on /media/fat/cifs (/media/fat is the root of the SD card).
#  NOTE: /media/fat/cifs is a special location that the mister binary will try before looking in
# the standard games location of /media/fat/games, so "cifs" is the suggested setting.
#- It can be a pipe "|" separated list of directories, i.e. "Amiga|C64|NES|SNES",
#  so the share subdirectiories with those names,
#  i.e. \\NAS\MiSTer\Amiga, \\NAS\MiSTer\C64, \\NAS\MiSTer\NES and \\NAS\MiSTer\SNES
#  will be mounted on local /media/fat/Amiga, /media/fat/C64, /media/fat/NES and /media/fat/SNES.
#- It can be an asterisk "*": when SINGLE_CIFS_CONNECTION="true",
#  all the directories in the remote share will be listed and mounted locally,
#  except the special ones (i.e. linux and config);
#  when SINGLE_CIFS_CONNECTION="false" all the directories in the SD root,
#  except the special ones (i.e. linux and config), will be mounted when one
#  with a matching name is found on the remote share.
LOCAL_DIR="cifs"

#Optional additional mount options, when in doubt leave blank.
#If you have problems not related to username/password, you can try "vers=2.0" or "vers=3.0".
ADDITIONAL_MOUNT_OPTIONS=""

#"true" in order to wait for the CIFS server to be reachable;
#useful when using this script at boot time.
WAIT_FOR_SERVER="true"

#"true" for automounting CIFS shares at boot time;
#it will create start/kill scripts in /etc/network/if-up.d and /etc/network/if-down.d.
MOUNT_AT_BOOT="false"



#========= ADVANCED OPTIONS =========
BASE_PATH="/media/fat"
#MISTER_CIFS_URL="https://github.com/MiSTer-devel/CIFS_MiSTer"
KERNEL_MODULES="md4.ko|md5.ko|des_generic.ko|fscache.ko|cifs.ko"
IFS="|"
SINGLE_CIFS_CONNECTION="true"
#Pipe "|" separated list of directories which will never be mounted when LOCAL_DIR="*"
SPECIAL_DIRECTORIES="config|linux|System Volume Information"



#=========CODE STARTS HERE=========

ORIGINAL_SCRIPT_PATH="$0"
if [ "$ORIGINAL_SCRIPT_PATH" == "bash" ]
then
	ORIGINAL_SCRIPT_PATH=$(ps | grep "^ *$PPID " | grep -o "[^ ]*$")
fi
INI_PATH=${ORIGINAL_SCRIPT_PATH%.*}.ini
if [ -f $INI_PATH ]
then
	eval "$(cat $INI_PATH | tr -d '\r')"
fi

# Function to unmount /media/fat if already mounted
unmount_media_fat() {
    if mount | grep -q "on $BASE_PATH "; then
        echo "Unmounting existing $BASE_PATH..."
        # First try to unmount any bind mounts
        mount | grep "on $BASE_PATH/" | awk '{print $3}' | sort -r | while read -r MOUNTED_DIR; do
            umount "$MOUNTED_DIR" 2>/dev/null
        done
        # Then unmount the main mount
        umount "$BASE_PATH" 2>/dev/null
        # Also check for any temp mounts
        mount | grep "/tmp/.*$" | awk '{print $3}' | while read -r TEMP_DIR; do
            umount "$TEMP_DIR" 2>/dev/null
        done
        sleep 1
        echo "$BASE_PATH unmounted"
    fi
}

# Global flag to track if selection was auto-selected
AUTO_SELECTED=false

# Function to display menu and get user selection
show_menu() {
    local num_shares=${#SHARE_CONFIGS[@]}
    
    if [ $num_shares -eq 0 ]; then
        echo "ERROR: No shares configured!"
        echo "Please edit ${ORIGINAL_SCRIPT_PATH##*/}"
        echo "and add share definitions."
        exit 1
    fi
    
    echo "=================================="
    echo "    MiSTer CIFS Mount Menu"
    echo "=================================="
    echo ""
    
    local idx=1
    for config in "${SHARE_CONFIGS[@]}"; do
        IFS='|' read -r srv prt shr shrdir usr pwd dom desc <<< "$config"
        local default_marker=""
        if [ "$DEFAULT_SELECTION" -eq "$idx" ]; then
            default_marker=" [DEFAULT]"
        fi
        echo "  $idx) $desc$default_marker"
        echo "     Server: $srv:$prt  Share: $shr$([ -n "$shrdir" ] && echo "/$shrdir")"
        idx=$((idx + 1))
    done
    
    echo ""
    echo "  0) Exit without mounting"
    echo ""
    
    if [ "$MENU_TIMEOUT" -gt 0 ] && [ "$DEFAULT_SELECTION" -gt 0 ] && [ "$DEFAULT_SELECTION" -le "$num_shares" ]; then
        echo "Press any key to choose mapping (or default will be chosen in $MENU_TIMEOUT seconds)..."
        
        # Wait for any keypress with timeout
        read -n 1 -t "$MENU_TIMEOUT" -s
        local key_pressed=$?
        
        echo "" # New line after prompt
        
        if [ $key_pressed -eq 0 ]; then
            # Key was pressed - show menu and wait indefinitely for selection
            echo "Manual selection - take your time..."
            echo ""
            read -p "Enter selection [0-$num_shares]: " SELECTION
        else
            # Timeout occurred - use default
            SELECTION=$DEFAULT_SELECTION
            AUTO_SELECTED=true
            echo "Timeout - using default selection: $SELECTION"
        fi
    else
        read -p "Enter selection [0-$num_shares]: " SELECTION
    fi
    
    echo ""
    
    # Validate selection
    if ! [[ "$SELECTION" =~ ^[0-9]+$ ]] || [ "$SELECTION" -lt 0 ] || [ "$SELECTION" -gt "$num_shares" ]; then
        echo "Invalid selection!"
        exit 1
    fi
    
    if [ "$SELECTION" -eq 0 ]; then
        echo "Exiting..."
        exit 0
    fi
    
    # Parse selected configuration (convert 1-based selection to 0-based array index)
    local array_index=$((SELECTION-1))
    local selected_config="${SHARE_CONFIGS[$array_index]}"
    
    # Save IFS and restore after parsing
    local OLD_IFS="$IFS"
    IFS='|'
    read -r SERVER PORT SHARE SHARE_DIRECTORY USERNAME PASSWORD DOMAIN DESCRIPTION <<< "$selected_config"
    IFS="$OLD_IFS"
    
    echo "Selected: Option $SELECTION - $DESCRIPTION"
#    echo "Debug: Array index=$array_index, Config=$selected_config"
    echo ""
}

# Show menu to select share (unless running from boot script)
if [ "$MOUNT_AT_BOOT" != "true" ]; then
    show_menu
fi

# Validate we have required configuration
if [ "$SERVER" == "" ] || [ "$PORT" == "" ] || [ "$SHARE" == "" ]
then
	echo "ERROR: Invalid configuration"
	echo "Please check share definitions"
	exit 1
fi 

for KERNEL_MODULE in $KERNEL_MODULES; do
	if ! cat /lib/modules/$(uname -r)/modules.builtin | grep -q "$(echo "$KERNEL_MODULE" | sed 's/\./\\\./g')"
	then
		if ! lsmod | grep -q "${KERNEL_MODULE%.*}"
		then
			echo "The current Kernel doesn't"
			echo "support CIFS (SAMBA)."
			echo "Please update your"
			echo "MiSTer Linux system."
			exit 1
#			if ! insmod "/media/fat/linux/$KERNEL_MODULE" > /dev/null 2>&1
#			then
#				echo "Downloading $KERNEL_MODULE"
#				curl -L "$MISTER_CIFS_URL/blob/master/$KERNEL_MODULE?raw=true" -o "/media/fat/linux/$KERNEL_MODULE"
#				case $? in
#					0)
#						;;
#					60)
#						if ! curl -kL "$MISTER_CIFS_URL/blob/master/$KERNEL_MODULE?raw=true" -o "/media/fat/linux/$KERNEL_MODULE"
#						then
#							echo "No Internet connection"
#							exit 2
#						fi
#						;;
#					*)
#						echo "No Internet connection"
#						exit 2
#						;;
#				esac
#				if ! insmod "/media/fat/linux/$KERNEL_MODULE" > /dev/null 2>&1
#				then
#					echo "Unable to load $KERNEL_MODULE"
#					exit 1
#				fi
#			fi
		fi
	fi
done

if [ "$(basename "ORIGINAL_SCRIPT_PATH")" != "mount_cifs.sh" ]
then
	if [ -f "/etc/network/if-up.d/mount_cifs" ] || [ -f "/etc/network/if-down.d/mount_cifs" ]
	then
		mount | grep "on / .*[(,]ro[,$]" -q && RO_ROOT="true"
		[ "$RO_ROOT" == "true" ] && mount / -o remount,rw
		rm "/etc/network/if-up.d/mount_cifs" > /dev/null 2>&1
		rm "/etc/network/if-down.d/mount_cifs" > /dev/null 2>&1
		sync
		[ "$RO_ROOT" == "true" ] && mount / -o remount,ro
	fi
fi
NET_UP_SCRIPT="/etc/network/if-up.d/$(basename ${ORIGINAL_SCRIPT_PATH%.*})"
NET_DOWN_SCRIPT="/etc/network/if-down.d/$(basename ${ORIGINAL_SCRIPT_PATH%.*})"
if [ "$MOUNT_AT_BOOT" ==  "true" ]
then
	WAIT_FOR_SERVER="true"
	if [ ! -f "$NET_UP_SCRIPT" ] || [ ! -f "$NET_DOWN_SCRIPT" ]
	then
		mount | grep "on / .*[(,]ro[,$]" -q && RO_ROOT="true"
		[ "$RO_ROOT" == "true" ] && mount / -o remount,rw
		echo "#!/bin/bash"$'\n'"$(realpath "$ORIGINAL_SCRIPT_PATH") &" > "$NET_UP_SCRIPT"
		chmod +x "$NET_UP_SCRIPT"
		echo "#!/bin/bash"$'\n'"umount -a -t cifs" > "$NET_DOWN_SCRIPT"
		chmod +x "$NET_DOWN_SCRIPT"
		sync
		[ "$RO_ROOT" == "true" ] && mount / -o remount,ro
	fi
else
	if [ -f "$NET_UP_SCRIPT" ] || [ -f "$NET_DOWN_SCRIPT" ]
	then
		mount | grep "on / .*[(,]ro[,$]" -q && RO_ROOT="true"
		[ "$RO_ROOT" == "true" ] && mount / -o remount,rw
		rm "$NET_UP_SCRIPT" > /dev/null 2>&1
		rm "$NET_DOWN_SCRIPT" > /dev/null 2>&1
		sync
		[ "$RO_ROOT" == "true" ] && mount / -o remount,ro
	fi
fi

# Unmount /media/fat if it's already mounted
unmount_media_fat

if [ "$USERNAME" == "" ]
then
	MOUNT_OPTIONS="sec=none"
else
	MOUNT_OPTIONS="username=$USERNAME,password=$PASSWORD"
	if [ "$DOMAIN" != "" ]
	then
		MOUNT_OPTIONS="$MOUNT_OPTIONS,domain=$DOMAIN"
	fi
fi

# Add port option if not standard SMB port 445
if [ "$PORT" != "" ] && [ "$PORT" != "445" ]
then
	MOUNT_OPTIONS="$MOUNT_OPTIONS,port=$PORT"
fi

if [ "$ADDITIONAL_MOUNT_OPTIONS" != "" ]
then
	MOUNT_OPTIONS="$MOUNT_OPTIONS,$ADDITIONAL_MOUNT_OPTIONS"
fi

if ! echo "$SERVER" | grep -q "^[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}$"
then
	if iptables -L > /dev/null 2>&1; then IPTABLES_SUPPORT="true"; else IPTABLES_SUPPORT="false"; fi
	[ "$IPTABLES_SUPPORT" == "true" ] && if iptables -C INPUT -p udp --sport 137 -j ACCEPT > /dev/null 2>&1; then PRE_EXISTING_FIREWALL_RULE="true"; else PRE_EXISTING_FIREWALL_RULE="false"; fi
	[ "$IPTABLES_SUPPORT" == "true" ] && [ "$PRE_EXISTING_FIREWALL_RULE" == "false" ] && iptables -I INPUT -p udp --sport 137 -j ACCEPT > /dev/null 2>&1
	if [ "$WAIT_FOR_SERVER" == "true" ]
	then
		echo "Waiting for $SERVER"
		until nmblookup $SERVER &>/dev/null
		do
			[ "$IPTABLES_SUPPORT" == "true" ] && [ "$PRE_EXISTING_FIREWALL_RULE" == "false" ] && iptables -D INPUT -p udp --sport 137 -j ACCEPT > /dev/null 2>&1
			sleep 1
			[ "$IPTABLES_SUPPORT" == "true" ] && if iptables -C INPUT -p udp --sport 137 -j ACCEPT > /dev/null 2>&1; then PRE_EXISTING_FIREWALL_RULE="true"; else PRE_EXISTING_FIREWALL_RULE="false"; fi
			[ "$IPTABLES_SUPPORT" == "true" ] && [ "$PRE_EXISTING_FIREWALL_RULE" == "false" ] && iptables -I INPUT -p udp --sport 137 -j ACCEPT > /dev/null 2>&1
		done
	fi
	# Get first non-Docker, non-link-local IP from nmblookup results
	# Filters out 172.x.x.x (Docker), 169.254.x.x (link-local), prefers 192.168.x.x
	SERVER=$(nmblookup $SERVER | grep -v "^172\." | grep -v "^169\.254\." | awk 'NR==1{print $1}')
	[ "$IPTABLES_SUPPORT" == "true" ] && [ "$PRE_EXISTING_FIREWALL_RULE" == "false" ] && iptables -D INPUT -p udp --sport 137 -j ACCEPT > /dev/null 2>&1
else
	if [ "$WAIT_FOR_SERVER" == "true" ]
	then
		echo "Waiting for $SERVER"
		until ping -q -w1 -c1 $SERVER &>/dev/null
		do
			sleep 1
		done
	fi
fi

MOUNT_SOURCE="//$SERVER/$SHARE"
[ "$SHARE_DIRECTORY" != "" ] && MOUNT_SOURCE+=/$SHARE_DIRECTORY

echo "Mounting: $MOUNT_SOURCE"
echo "Target: $BASE_PATH/$LOCAL_DIR"
echo ""

if [ "$LOCAL_DIR" == "*" ] || { echo "$LOCAL_DIR" | grep -q "|"; }
then
	if [ "$SINGLE_CIFS_CONNECTION" == "true" ]
	then
		SCRIPT_NAME=${ORIGINAL_SCRIPT_PATH##*/}
		SCRIPT_NAME=${SCRIPT_NAME%.*}
		mkdir -p "/tmp/$SCRIPT_NAME" > /dev/null 2>&1
		if mount -t cifs "$MOUNT_SOURCE" "/tmp/$SCRIPT_NAME" -o "$MOUNT_OPTIONS"
		then
			echo "$MOUNT_SOURCE mounted"
			if [ "$LOCAL_DIR" == "*" ]
			then
				LOCAL_DIR=""
				for DIRECTORY in "/tmp/$SCRIPT_NAME"/*
				do
					if [ -d "$DIRECTORY" ]
					then
						DIRECTORY=$(basename "$DIRECTORY")
						for SPECIAL_DIRECTORY in $SPECIAL_DIRECTORIES
						do
							if [ "$DIRECTORY" == "$SPECIAL_DIRECTORY" ]
							then
								DIRECTORY=""
								break
							fi
						done
						if [ "$DIRECTORY" != "" ]
						then
							if [ "$LOCAL_DIR" != "" ]
							then
								LOCAL_DIR="$LOCAL_DIR|"
							fi
							LOCAL_DIR="$LOCAL_DIR$DIRECTORY"
						fi
					fi
				done
			fi
			for DIRECTORY in $LOCAL_DIR
			do
				mkdir -p "$BASE_PATH/$DIRECTORY" > /dev/null 2>&1
				if mount --bind "/tmp/$SCRIPT_NAME/$DIRECTORY" "$BASE_PATH/$DIRECTORY"
				then
					echo "$DIRECTORY mounted"
				else
					echo "$DIRECTORY not mounted"
				fi
			done
		else
			echo "$MOUNT_SOURCE not mounted"
		fi
	else
		if [ "$LOCAL_DIR" == "*" ]
		then
			LOCAL_DIR=""
			for DIRECTORY in "$BASE_PATH"/*
			do
				if [ -d "$DIRECTORY" ]
				then
					DIRECTORY=$(basename "$DIRECTORY")
					for SPECIAL_DIRECTORY in $SPECIAL_DIRECTORIES
					do
						if [ "$DIRECTORY" == "$SPECIAL_DIRECTORY" ]
						then
							DIRECTORY=""
							break
						fi
					done
					if [ "$DIRECTORY" != "" ]
					then
						if [ "$LOCAL_DIR" != "" ]
						then
							LOCAL_DIR="$LOCAL_DIR|"
						fi
						LOCAL_DIR="$LOCAL_DIR$DIRECTORY"
					fi
				fi
			done
		fi
		for DIRECTORY in $LOCAL_DIR
		do
			mkdir -p "$BASE_PATH/$DIRECTORY" > /dev/null 2>&1
			if mount -t cifs "$MOUNT_SOURCE" "$BASE_PATH/$DIRECTORY" -o "$MOUNT_OPTIONS"
			then
				echo "$DIRECTORY mounted"
			else
				echo "$DIRECTORY not mounted"
			fi
		done
	fi
else
	mkdir -p "$BASE_PATH/$LOCAL_DIR" > /dev/null 2>&1
	if mount -t cifs "$MOUNT_SOURCE" "$BASE_PATH/$LOCAL_DIR" -o "$MOUNT_OPTIONS"
	then
			echo "$LOCAL_DIR mounted"
	else
			echo "$LOCAL_DIR mounted"
	fi
fi

echo "Done!"

# Wait for keypress only if user manually made a selection
if [ "$AUTO_SELECTED" = false ] && [ "$MOUNT_AT_BOOT" != "true" ]; then
    echo ""
    read -n 1 -s -r -p "Press any key to exit..."
    echo ""
fi

exit 0
