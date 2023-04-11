"""
    Fetch GPU load data from a remote server using SSH.
"""
import argparse
import configparser
import io
from fabric import Connection
import pandas as pd
import invoke


def get_username(pid, hostname, user, key_filename):
    """Get the corresponding username for a PID"""
    SSH_CMD = 'ps -o user= {}'.format(pid)

    # sometimes zombies occur...
    try:
        result = Connection(hostname, user=user, connect_kwargs={"key_filename": key_filename}).run(SSH_CMD, hide=True).stdout
        result = str.strip(result)
    except invoke.exceptions.UnexpectedExit:
        result = None

    return result


def get_gpu_processes(hostname, user, key_filename):
    SSH_CMD = 'nvidia-smi --query-compute-apps=pid,gpu_uuid --format=csv'

    result = Connection(hostname, user=user, connect_kwargs={"key_filename": key_filename}).run(SSH_CMD, hide=True).stdout  # does return a CSV

    csv = io.StringIO(result)  # temporary string stream
    csv = pd.read_csv(csv)  # parse as csv
    csv['username'] = ''
    csv = csv.rename(columns={' gpu_uuid': 'gpu_uuid'})

    for cur_idx, cur_row in csv.iterrows():
        username = get_username(cur_row['pid'], hostname, user, key_filename)

        if username is None:
            username = 'Zombie'

        csv.loc[cur_idx, 'username'] = username

    return csv


def get_load_data(hostname, user, key_filename):
    """Get the output from `nvidia-smi` and parse it."""
    SSH_CMD = 'nvidia-smi --query-gpu=utilization.gpu,utilization.memory,index,gpu_name,gpu_uuid --format=csv'

    result = Connection(hostname, user=user, connect_kwargs={"key_filename": key_filename}).run(SSH_CMD, hide=True).stdout  # does return a CSV

    csv = io.StringIO(result)  # temporary string stream
    csv = pd.read_csv(csv)  # parse as csv

    csv = csv.rename(columns={'utilization.gpu [%]': 'load',
                              ' utilization.memory [%]': 'load_mem',
                              ' name': 'gpu_name',
                              ' uuid': 'gpu_uuid',
                              ' index': 'gpu_idx'})

    csv['load'] = csv['load'].map(lambda x: int(x.rstrip('%')))
    csv['load_mem'] = csv['load_mem'].map(lambda x: int(x.rstrip('%')))
    csv['hostname'] = cur_host  # add column with hostname

    return csv


def get_data(hostname, user, key_filename):
    load_data = get_load_data(hostname, user, key_filename)
    load_data['username'] = ''

    # get processes on the gpus
    process_data = get_gpu_processes(hostname, user, key_filename)
    
    if not process_data.empty:
        # combine load data with username through gpu_uuid
        for cur_idx, cur_row in load_data.iterrows():
            if not process_data[process_data['gpu_uuid'] == cur_row['gpu_uuid']].empty:
                username = process_data[process_data['gpu_uuid'] == cur_row['gpu_uuid']]['username'].values

                load_data.loc[cur_idx, 'username'] = ', '.join(username)
    
    return load_data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('-c', type=str, default='config.ini', help='path to config file')
    args = parser.parse_args()

    # parse config file
    config = configparser.ConfigParser()
    config.read(args.c)

    # get list of hosts from config
    HOSTS = str.split(config['common']['hosts'], ',')

    results = []

    for cur_host in HOSTS:
        csv = get_data(cur_host, config['common']['user'], config['common']['key_filename'])
        results.append(csv)
    
    results = pd.concat(results)
    results.to_csv('load_data.csv')
