from ibkr_desk.core.pubsub import Broker


def test_publish_delivers_to_subscriber():
    broker = Broker()
    q = broker.subscribe("topic.a")
    broker.publish("topic.a", {"value": 1})
    assert q.get_nowait() == {"value": 1}


def test_publish_ignores_unrelated_topics():
    broker = Broker()
    q = broker.subscribe("topic.a")
    broker.publish("topic.b", {"value": 1})
    assert q.empty()


def test_full_queue_drops_oldest_message():
    broker = Broker(max_queue_size=2)
    q = broker.subscribe("topic.a")
    broker.publish("topic.a", 1)
    broker.publish("topic.a", 2)
    broker.publish("topic.a", 3)  # queue was full at 2 -- oldest (1) should be dropped
    assert q.get_nowait() == 2
    assert q.get_nowait() == 3
    assert q.empty()


def test_unsubscribe_stops_delivery():
    broker = Broker()
    q = broker.subscribe("topic.a")
    broker.unsubscribe("topic.a", q)
    broker.publish("topic.a", "hello")
    assert q.empty()
