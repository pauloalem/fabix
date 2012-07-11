from __future__ import print_function
import sys
import time
from datetime import datetime

import boto
from boto.ec2.autoscale import (LaunchConfiguration, AutoScalingGroup,
    ScalingPolicy)
from fabric.decorators import task
from fabric.operations import puts
from fabric.utils import abort


@task
def create_ami(instance_id, name):
    """
    Create AMI image from specified instance

    The instance needs to be shutdown before the creation begin.
    """
    image_name = "{0}_{1}".format(name, datetime.now().strftime("%Y%m%d-%H%M"))

    conn = boto.connect_ec2()
    image_id = conn.create_image(instance_id=instance_id, name=image_name)
    puts("Creating AMI {0} for instance {1}".format(image_name, image_id))

    while True:
        puts('.', end='', sep='')
        sys.stdout.flush()

        image = conn.get_image(image_id)
        if image.state == 'available':
            break
        if image.state == "failed":
            abort("Error creating AMI for {1}".format(image_id))
        time.sleep(5.0)

    puts("Image {0} created".format(image_name))
    return image_id


def create_scaling_policy(conn, name, as_name, scaling_adjustment, cooldown):
    scaling_policy = ScalingPolicy(name=name, as_name=as_name,
                                   adjustment_type='ChangeInCapacity',
                                   scaling_adjustment=scaling_adjustment,
                                   cooldown=cooldown)
    conn.create_scaling_policy(scaling_policy)


@task
def setup_autoscale(name, ami_id, key_name, security_groups, load_balancers,
        instance_type='m1.micro', availability_zones=['us-east-1b'],
        min_instances=1, max_instances=12,
        sp_up_adjustment=1, sp_up_cooldown=180,
        sp_down_adjustment=-1, sp_down_cooldown=180,
        instance_monitoring=True
    ):
    """
    Configure AutoScaling for Amazon EC2 instances

        `name`: name used to identify the autoscale group
        `ami_id`: AMI ID from instances will be generated
        `key_name`: name of the SSH key which will have access to the instance
        `security_groups`: list of security groups to associate with each
                           created instance
        `instance_type`: type of the instance that will be launched
                         (see http://aws.amazon.com/ec2/instance-types/)
        `availability_zones`: in which zones instances can be launched. This
                              must match with zones configured in ELB.
        `min_instances`: minimal number of instances that must be running
        `max_instances`: maximum number of instance that must be running
        `sp_up_adjustment`: sets the number of instances to launch on the up
                            scaling policy trigger
        `sp_down_adjustment`: sets the number of instances to kill on the down
                            scaling policy trigger
    """
    launch_config = "{0}_{1}".format(name, datetime.now().strftime("%Y%m%d-%H%M"))
    group_name = '{0}-as-group'.format(name)

    sp_up_name = '{0}-scaling-up'.format(name)
    sp_down_name = '{0}-scaling-down'.format(name)

    conn_as = boto.connect_autoscale()
    import pdb; pdb.set_trace()
    lc = LaunchConfiguration(name=launch_config, image_id=ami_id,
                             key_name=key_name,
                             security_groups=security_groups,
                             instance_type=instance_type,
                             instance_monitoring=instance_monitoring)
    conn_as.create_launch_configuration(lc)

    ag = AutoScalingGroup(group_name=group_name, load_balancers=load_balancers,
                          availability_zones=availability_zones,
                          launch_config=launch_config,
                          min_size=min_instances, max_size=max_instances)
    conn_as.create_auto_scaling_group(ag)

    create_scaling_policy(conn_as, sp_up_name, group_name, sp_up_adjustment, sp_up_cooldown)
    create_scaling_policy(conn_as, sp_down_name, group_name, sp_down_adjustment, sp_down_cooldown)


def get_autoscaling_instances(elb_name):
    """Get public DNS from autoscaling instances registered with ELB `elb_name`."""
    elb_conn = boto.connect_elb()
    loadbalancers = elb_conn.get_all_load_balancers([elb_name])

    instances_ids = []
    for instance in loadbalancers[0].instances:
        instances_ids.append(instance.id)

    ec2_conn = boto.connect_ec2()
    reservations = ec2_conn.get_all_instances(instances_ids)

    ec2_instances = []
    for reservation in reservations:
        ec2_instances.append(reservation.instances[0].public_dns_name)
    return ec2_instances