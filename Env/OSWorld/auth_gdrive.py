import os, sys
os.chdir("/mnt/zhaorunsong/repo/CUA/Env/OSWorld")
sys.path.insert(0, ".")
from pydrive.auth import GoogleAuth

gauth = GoogleAuth(settings_file="evaluation_examples/settings/googledrive/settings.yml")
gauth.LocalWebserverAuth(host_name="localhost", port_numbers=[8080])
print("授权成功！credentials.json 已保存。")
