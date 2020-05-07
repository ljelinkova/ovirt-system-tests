#!/usr/bin/python
import shutil
from test_utils.navigation.driver import *
from datetime import datetime
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
import ost_utils.selenium.docker as docker

test_file = __import__('100_basic_ui_sanity_pytest')

engine_ip = '192.168.1.107'
engine_fqdn = 'engine'
engine_url = "https://%s:8443/ovirt-engine/webadmin" % engine_fqdn
engine_username = 'admin'
engine_password = 'a'
engine_cert = '/tmp/pki-resource'

def hub_url():
    with docker.grid(engine_fqdn, engine_ip) as hub_url:
        yield hub_url

def firefox_capabilities():
    capabilities = DesiredCapabilities.FIREFOX.copy()
    capabilities['platform'] = test_file.BROWSER_PLATFORM
    capabilities['version'] = test_file.FIREFOX_VERSION
    capabilities['browserName'] = 'firefox'
    capabilities['acceptInsecureCerts'] = True
    # https://bugzilla.mozilla.org/show_bug.cgi?id=1538486
    capabilities['moz:useNonSpecCompliantPointerOrigin'] = True
    return capabilities

def chrome_capabilities():
    capabilities = DesiredCapabilities.CHROME.copy()
    capabilities['platform'] = test_file.BROWSER_PLATFORM
    capabilities['version'] = test_file.CHROME_VERSION
    capabilities['acceptInsecureCerts'] = True
    return capabilities

def ovirt_driver(capabilities, hub_url, engine_webadmin_url):
    driver = webdriver.Remote(
        command_executor=hub_url,
        desired_capabilities=capabilities
    )

    ovirt_driver = Driver(driver)
    driver.set_window_size(test_file.WINDOW_WIDTH, test_file.WINDOW_HEIGHT)
    driver.get(engine_webadmin_url)
    return ovirt_driver

def screenshots_dir():
    path = '/tmp/screenshots'
    # make screenshot directory
    if os.path.exists(path):
        # clean up old directory
        shutil.rmtree(path)
    os.makedirs(path)
    return path

def save_screenshot(ovirt_driver, browser_name, screenshots_dir):

    def save(description, delay=1):
        date = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        name = "{}_{}_{}.png".format(date, browser_name, description)
        path = os.path.join(screenshots_dir, name)
        ovirt_driver.save_screenshot(path, delay)

    return save

def save_page_source(ovirt_driver, browser_name, screenshots_dir):

    def save(description, delay=1):
        date = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        name = "{}_{}_{}.html".format(date, browser_name, description)
        path = os.path.join(screenshots_dir, name)
        ovirt_driver.save_page_source(path, delay)

    return save

hub_url_gen = hub_url()
hub_url = next(hub_url_gen)

capabilities = firefox_capabilities()
browser_name = capabilities['browserName']
ovirt_driver = ovirt_driver(capabilities, hub_url, engine_url)
screenshots_dir = screenshots_dir()
save_screenshot = save_screenshot(ovirt_driver, browser_name, screenshots_dir)
save_page_source = save_page_source(ovirt_driver, browser_name, screenshots_dir)

try:
    test_file.test_login(ovirt_driver, save_screenshot, engine_username, engine_password, engine_cert)
    test_file.test_left_nav(ovirt_driver, save_screenshot, save_page_source)
    test_file.test_virtual_machines(ovirt_driver, None, save_screenshot, save_page_source)
finally:
    hub_url_gen = None
