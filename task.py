import os
import stat
import posixpath
import paramiko
from getpass import getpass

# -----------------------------
# Read User Inputs
# -----------------------------
server_ip = input("Server IP: ")
username = input("Username: ")

auth_choice = input("Authentication Method - Password [p] or PEM Key [k] (default: p): ").strip().lower()
password = None
key_path = None

if auth_choice in ('k', 'key', 'pem'):
    key_path = input("PEM Key Path: ").strip()
else:
    password = getpass("Password: ")

folder_path = input("Base Folder Path: ").strip()

# Example:
# folder_path = /home/builds
#
# It will search:
# /home/builds/dev
# /home/builds/prod

DEV_PATH = posixpath.join(folder_path, "dev")
PROD_PATH = posixpath.join(folder_path, "prod")

# Hardcoded local dummy directories
LOCAL_DEV_DIR = r"c:\Users\User\Desktop\code\path\dummy\dev"
LOCAL_PROD_DIR = r"c:\Users\User\Desktop\code\path\dummy\prod"


# -----------------------------
# SSH Connection
# -----------------------------
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    connect_kwargs = {
        "hostname": server_ip,
        "username": username,
    }
    if key_path:
        connect_kwargs["key_filename"] = key_path
    else:
        connect_kwargs["password"] = password

    ssh.connect(**connect_kwargs)

    sftp = ssh.open_sftp()

    def is_executable(mode):
        return bool(mode & stat.S_IXUSR)

    def classify_executable(remote_path, item):
        filename = item.filename.lower()
        
        # 1. Windows .exe file
        if filename.endswith(".exe"):
            return 'windows'
        
        # 2. Executable permission check
        if is_executable(item.st_mode):
            # Try reading ELF header to differentiate Linux vs ARM
            try:
                with sftp.open(remote_path, 'rb') as f:
                    header = f.read(64)
                    if header.startswith(b'\x7fELF') and len(header) >= 20:
                        # ELF machine field is at bytes 18-19
                        machine = header[18] | (header[19] << 8)
                        if machine in (40, 183): # EM_ARM, EM_AARCH64
                            return 'arm'
                        elif machine in (3, 62): # EM_386, EM_X86_64
                            return 'linux'
            except Exception:
                pass
            
            # Fallback to filename-based check
            if "arm" in filename or "aarch64" in filename:
                return 'arm'
            else:
                return 'linux'
        return None

    def search_executables(remote_path):
        """
        Searches recursively for:
        Linux executables, Windows .exe, ARM binaries, Data files
        """
        result = {
            "linux": [],
            "windows": [],
            "arm": []
        }

        def walk(path):
            try:
                for item in sftp.listdir_attr(path):
                    full_path = posixpath.join(path, item.filename)
                    if stat.S_ISDIR(item.st_mode):
                        walk(full_path)
                    else:
                        category = classify_executable(full_path, item)
                        if category:
                            result[category].append(full_path)
            except Exception as e:
                print(f"Warning: Could not list directory {path}: {e}")

        walk(remote_path)
        return result

    def download_results(results, remote_base_path, local_base_dir):
        """
        Downloads the files in results dictionary to local_base_dir,
        preserving the categories: 'windows', 'linux', 'arm' and their relative directory structure.
        """
        print(f"\nDownloading files from {remote_base_path} to {local_base_dir}...")
        for category, remote_paths in results.items():
            category_dir = os.path.join(local_base_dir, category)
            for remote_path in remote_paths:
                try:
                    rel_path = posixpath.relpath(remote_path, remote_base_path)
                except ValueError:
                    rel_path = posixpath.basename(remote_path)
                
                local_path = os.path.join(category_dir, rel_path.replace('/', os.sep))
                
                # Ensure the local parent directory exists
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                
                print(f"[{category.upper()}] Downloading {remote_path} -> {local_path} ...")
                try:
                    sftp.get(remote_path, local_path)
                    print("  Success")
                except Exception as e:
                    print(f"  Error: {e}")

    print("\nSearching DEV...")
    dev_result = search_executables(DEV_PATH)

    print("Searching PROD...")
    prod_result = search_executables(PROD_PATH)

    print("\n========== DEV ==========")
    print(dev_result)

    print("\n========== PROD ==========")
    print(prod_result)

    # Download found files
    download_results(dev_result, DEV_PATH, LOCAL_DEV_DIR)
    download_results(prod_result, PROD_PATH, LOCAL_PROD_DIR)

finally:
    ssh.close()