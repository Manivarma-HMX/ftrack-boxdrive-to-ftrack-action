# -*- coding: utf-8 -*-
# Part of Box to Ftrack Action v1.2 - Dec/2021
import os
import re
import sys
import shutil

from boxsdk import Client
from boxsdk.auth.jwt_auth import JWTAuth

config_file = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "config.json")
)
auth = JWTAuth.from_settings_file(config_file)
client = Client(auth)


def download_to_path(item, path):
    f = open(os.path.join(path, item["name"]), "wb")
    item.download_to(f)
    f.close()


def get_box_item(item, path):
    if item["type"] == "file":
        download_to_path(item, path)
        return

    for item in item.get_items():
        if item["type"] == "folder":
            folderPath = os.path.join(path, item["name"])
            if not os.path.exists(folderPath):
                os.mkdir(folderPath)
            get_box_item(item, folderPath)
        if item["type"] == "file":
            download_to_path(item, path)


def find_box_item(id, box_items):
    # Find item using its Box ID
    for item in box_items.get_items():
        if item["type"] == "folder":
            if item["id"] == id:
                get_box_item(item, storage_path)
                return
            else:
                find_box_item(id, item)
        else:
            if item["id"] == id:
                get_box_item(item, storage_path)
                return


def make_root_path(item, path):
    # Temporary storage location
    if item["type"] == "folder":
        tempName = "box_" + item["name"]
        temp_path = os.path.join(path, tempName)
    elif item["type"] == "file":
        tempName = "box_" + os.path.splitext(item["name"])[0]
        temp_path = os.path.join(path, tempName)

    if not os.path.exists(temp_path):
        os.mkdir(temp_path)

    return temp_path


def process_shared_link(link, path):
    # Gathering content information from URL
    share_prefix = "https://app.box.com/s/"
    rootLink = re.findall(share_prefix + "\w+", link)[0]
    sub_item = re.split(rootLink, link)[-1]

    global storage_path
    if not sub_item:
        sharedItems = client.get_shared_item(link, None)
        storage_path = make_root_path(sharedItems, path)
        get_box_item(sharedItems, storage_path)
    else:
        sharedItems = client.get_shared_item(rootLink, None)
        storage_path = make_root_path(sharedItems, path)
        item_type, item_id = re.split("/", link)[-2:]
        find_box_item(item_id, sharedItems)


if __name__ == "__main__":
    # Removing any previously generated temporary box folder
    for item in next(os.walk(sys.argv[2]))[1]:
        if item.startswith("box_"):
            shutil.rmtree(
                os.path.join(sys.argv[2], item),
                ignore_errors=True,
            )

    process_shared_link(sys.argv[1], sys.argv[2])
    print(storage_path)
