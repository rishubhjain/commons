import sys
from tendrl.commons.event import Event
from tendrl.commons.message import Message

def log(log_priority,publisher_id,msg):
    try:
        Event(
            Message(
                priority=log_priority,
                publisher=publisher_id,
                payload={"message": msg}
                )
            )
    except KeyError:
            sys.stdout.write(msg)



        
