import plugins
from plugins import *
from common.log import logger
from .wenxb_plugin import WenXiaoBaiPlugin

def create():
    return WenXiaoBaiPlugin()

def destroy():
    pass 