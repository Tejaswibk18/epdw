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

# The script will search the entire base folder path for executables
# and copy all found files into both local dev and prod directories.

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
        Searches the base folder recursively for:
        Linux executables, Windows .exe, ARM binaries
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
        Downloads all found executables to the given local_base_dir,
        placing each file into its category subfolder (linux/windows/arm).
        """
        print(f"\nDownloading files from {remote_base_path} to {local_base_dir}...")
        for category, remote_paths in results.items():
            category_dir = os.path.join(local_base_dir, category)
            for remote_path in remote_paths:
                filename = posixpath.basename(remote_path)
                local_path = os.path.join(category_dir, filename)

                # Ensure the local category directory exists
                os.makedirs(category_dir, exist_ok=True)

                print(f"[{category.upper()}] {remote_path} -> {local_path} ...")
                try:
                    sftp.get(remote_path, local_path)
                    print("  Success")
                except Exception as e:
                    print(f"  Error: {e}")

    # Search the base folder path directly
    print(f"\nSearching in: {folder_path}")
    found = search_executables(folder_path)

    print("\n========== Found Executables ==========")
    for category, paths in found.items():
        print(f"  {category.upper()}: {len(paths)} file(s)")
        for p in paths:
            print(f"    - {p}")

    # Copy all found files into BOTH local dev and prod directories
    download_results(found, folder_path, LOCAL_DEV_DIR)
    download_results(found, folder_path, LOCAL_PROD_DIR)

    print("\nDone! Files saved to:")
    print(f"  DEV:  {LOCAL_DEV_DIR}")
    print(f"  PROD: {LOCAL_PROD_DIR}")

finally:
    ssh.close()