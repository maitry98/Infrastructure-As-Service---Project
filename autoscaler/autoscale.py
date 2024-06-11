import time
import boto3
import os

from dotenv import dotenv_values

MIN_INSTANCES = 1
MAX_INSTANCES = 20
SCALE_FACTOR = 3
COOLDOWN = 120


class AutoScale:
    def __init__(self, config):
        self.image_ami_id = 'ami-0f443623c38a6b7f8'
        self.instance_type = 't2.micro'
        self.subnet_id = "subnet-03513ad7b212b9a4b"
        self.key_name = 'project_iaas'
        self.security_group = "sg-07651c181a0fbcf21"
        self.availability_zone = "us-east-1a"
        self.instance_map = {}
        self.request_queue_url = config.get('REQUEST_QUEUE_URL')
        self.ec2_client = boto3.client('ec2', region_name=config.get('AWS_DEFAULT_REGION'),
                                       aws_access_key_id=config.get('AWS_ACCESS_KEY_ID'),
                                       aws_secret_access_key=config.get('AWS_SECRET_ACCESS_KEY'))

        self.sqs_client = boto3.client('sqs', region_name=config.get('AWS_DEFAULT_REGION'),
                                       aws_access_key_id=config.get('AWS_ACCESS_KEY_ID'),
                                       aws_secret_access_key=config.get('AWS_SECRET_ACCESS_KEY'))

    def create_instance(self, iid):
        try:
            block_device = [
                {
                    'DeviceName': "/dev/sdf",
                    'Ebs': {
                        'DeleteOnTermination': True,
                        'VolumeSize': 15,
                        'VolumeType': 'gp2'
                    }
                },
            ]

            response = self.ec2_client.run_instances(ImageId=self.image_ami_id,
                                                     InstanceType=self.instance_type,
                                                     SubnetId=self.subnet_id,
                                                     SecurityGroupIds=[self.security_group],
                                                     MinCount=1, MaxCount=1,
                                                     BlockDeviceMappings=block_device,
                                                     KeyName=self.key_name,
                                                     Placement={
                                                         'AvailabilityZone': self.availability_zone,
                                                     },
                                                     TagSpecifications=[
                                                         {
                                                             'ResourceType': 'instance',
                                                             'Tags': [
                                                                 {
                                                                     'Key': 'Name',
                                                                     'Value': "app-instance%s" % iid
                                                                 }
                                                             ]
                                                         }
                                                     ])

            if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                instance_id = response['Instances'][0]['InstanceId']
                # self.ec2_client.get_waiter('instance_running').wait(
                #     InstanceIds=[instance_id]
                # )
                print('Success! instance:', instance_id, 'is created and running')
                self.instance_map[iid] = instance_id
                return True
            return False
        except Exception as e:
            print(f"Failed to create instance: {e}")
            return False

    def remove_instance(self, iid):
        try:
            response = self.ec2_client.terminate_instances(
                InstanceIds=[
                    self.instance_map[iid],
                ],
                DryRun=False
            )
            if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                print('Success! instance:', self.instance_map[iid], 'is terminated')
                return True
            return False
        except Exception as e:
            print(f"Failed to remove instance: {e}")
            return False

    def scaleup(self, current, required):
        while current <= required and current < MAX_INSTANCES:
            current += 1
            self.create_instance(current)
            if current >= MAX_INSTANCES:
                return current
        return current

    def scaledown(self, current, required):
        while current >= required and current > MIN_INSTANCES:
            self.remove_instance(current)
            current -= 1
            if current <= MIN_INSTANCES:
                return current
        return current

    def get_total_msgs(self):
        try:
            response = self.sqs_client.get_queue_attributes(
                QueueUrl=self.request_queue_url,
                AttributeNames=['ApproximateNumberOfMessages']
            )
            total_msgs = int(response['Attributes']['ApproximateNumberOfMessages'])
            return total_msgs
        except Exception as e:
            print(f"Failed to get queue attributes: {e}")
            return 1


def main():
    config = dotenv_values()
    auto_scale_obj = AutoScale(config)
    current_instance_count = 1
    while True:
        total_msgs = auto_scale_obj.get_total_msgs()
        required_instance_count = int(total_msgs / SCALE_FACTOR)
        if required_instance_count > current_instance_count:
            if current_instance_count == MAX_INSTANCES:
                print("Max limit reached of %s instance" % current_instance_count)
                time.sleep(60)
            else:
                print(f"Messages in Input Queue: {total_msgs}. Scaling Up!")
                current_instance_count = auto_scale_obj.scaleup(current_instance_count, required_instance_count)
                time.sleep(COOLDOWN)
        elif required_instance_count <= current_instance_count:
            if current_instance_count == MIN_INSTANCES:
                print("Min limit reached of %s instance" % current_instance_count)
                time.sleep(60)
            else:
                print(f"Messages in Input Queue: {total_msgs}. Scaling Down!")
                current_instance_count = auto_scale_obj.scaledown(current_instance_count, required_instance_count)
                time.sleep(COOLDOWN)


if __name__ == "__main__":
    main()
