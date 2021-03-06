# Copyright 2020 Aeris Communications Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Implements a very simple geofence.

Uses the AerFrame Location APIs to determine if a device has moved in the
physical world by checking to see if it has moved in the cellular network.
It queries AerFrame for the location of the device once an hour and prints a message if the device has moved.

Note that, in the real world, this may not produce correct results:
* the device may remain in the same position, but move to a different part of the cellular network because,
for example, the device roamed to a different carrier.
* the device may move to a different cell, and then back to its original cell, and the hourly polling
will be unable to tell that the device moved.

If you're interested in more robust geofencing capabilities, Aeris may be able to help!
Drop us a line at https://www.aeris.com/get-connected/
"""

# Attempt to import the aerisapisdk from an installed package, or the checked-out source code otherwise
try:
    from aerisapisdk import aerframesdk
    from aerisapisdk import aerisconfig
    from aerisapisdk.exceptions import ApiException
    print('Using the aerisapisdk installed from pip')
except ModuleNotFoundError:
    print('Using the currently-checked-out aerisapisdk')
    import os
    import inspect
    import sys
    current_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    parent_dir = os.path.dirname(current_dir)
    sys.path.insert(0, parent_dir)
    from aerisapisdk import aerframesdk
    from aerisapisdk import aerisconfig
    from aerisapisdk.exceptions import ApiException

import argparse
import json
import logging
import sched
import time

# only query for location once an hour
LOCATION_REQUEST_PERIOD_SECONDS = 60*60
logger = None


def begin_loop(account_id, api_key, device_id, device_id_type):
    scheduler = sched.scheduler(time.time, time.sleep)
    scheduler.enter(1, 1, get_location_and_make_noise,
                    (account_id, api_key, device_id, device_id_type, scheduler, None))
    scheduler.run()


def get_location_and_make_noise(account_id, api_key, device_id, device_id_type, scheduler, original_location):
    try:
        new_location = aerframesdk.get_location(account_id, api_key, device_id_type, device_id)
        logger.debug(f'Latest location = {new_location}')
        # if there actually is a current location (instead of it being unknown...)
        if is_location_present(new_location):
            # set the original location to the current location
            if original_location is None:
                original_location = new_location
                logger.info(f'The original "stay-put" location of the device is {original_location}')

            # check to see if the location changed
            if location_changed(new_location, original_location):
                logger.warn(f'The device moved!')

    except ApiException as e:
        logger.error(f'There was a problem calling the API', exc_info=e)
    except BaseException as e:
        logger.error(f'Something else went horribly wrong', exc_info=e)

    # run this function again after some delay
    scheduler.enter(LOCATION_REQUEST_PERIOD_SECONDS, 1, get_location_and_make_noise,
                    (account_id, api_key, device_id, device_id_type, scheduler, original_location))


def is_location_present(loc):
    """
    Checks to see if a location result has actual data, or if it is the "no location available" response.

    Parameters
    ----------
    loc: dict

    Returns
    -------
    True if there is actually some location data in there.
    """
    if loc['mcc'] == 0:
        return False

    return True


def location_changed(new_loc, prev_loc):
    """
    Examines device locations to determine if a device has moved.
    Parameters
    ----------
    new_loc: dict
    prev_loc: dict

    Returns
    -------
    bool
        True if the device has moved.
    """
    result = False
    if prev_loc is None:
        return False
    for attribute in ('mcc', 'mnc', 'lac', 'cellId'):
        if new_loc[attribute] != prev_loc[attribute]:
            logger.warn(f'Device has moved from {attribute} {prev_loc[attribute]} to {new_loc[attribute]}')
            result = True
    return result


def configure_logging(level):
    global logger

    date_format_string = '%Y-%m-%dT%H:%M:%S%z'
    formatter = logging.Formatter(fmt='%(asctime)s %(levelname)s: %(message)s', datefmt=date_format_string)
    formatter.converter = time.gmtime

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)

    # root logger is good enough
    logger = logging.getLogger('aerframe_budget_geofence')
    logger.setLevel(level)
    logger.addHandler(ch)


if __name__ == '__main__':
    argparser = argparse.ArgumentParser()
    argparser.add_argument('--config-file', required=True,
                           help='path to a configuration file to use, like the one generated by aeriscli config')
    argparser.add_argument('--imsi', required=True, help='the IMSI you want to try to geofence')

    args = argparser.parse_args()

    # point aerisconfig at our configuration file
    aerisconfig.load_config(args.config_file)
    # load api key and account ID from the same configuration file
    with open(args.config_file, 'r') as f:
        config_dict = json.load(f)
    api_key = config_dict['apiKey']
    account_id = config_dict['accountId']
    del config_dict

    device_id = args.imsi
    device_id_type = 'IMSI'

    configure_logging(logging.INFO)
    logger.info('Starting...')

    # start the loop
    begin_loop(account_id, api_key, device_id, device_id_type)
