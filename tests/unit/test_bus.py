"""
Unit tests for AgentBus — message passing between agents (Phase D).
"""

from kerno.bus import BROADCAST, AgentBus, AgentMessage


class TestAgentBus:

    def test_send_receive_delivers_once(self):
        bus = AgentBus()
        bus.send_to("critic", "review", {"score": 42}, sender="analyst")
        assert bus.has_pending("critic")
        messages = bus.receive("critic")
        assert len(messages) == 1
        assert messages[0].sender == "analyst"
        assert messages[0].kind == "review"
        assert messages[0].payload == {"score": 42}
        assert not bus.has_pending("critic")   # consumed

    def test_pending_does_not_consume(self):
        bus = AgentBus()
        bus.send_to("critic", "note", {}, sender="analyst")
        assert len(bus.pending("critic")) == 1
        assert len(bus.pending("critic")) == 1   # still there

    def test_messages_addressed_to_others_not_delivered(self):
        bus = AgentBus()
        bus.send_to("critic", "note", {}, sender="analyst")
        assert bus.pending("narrator") == []
        assert bus.has_pending("narrator") is False

    def test_broadcast_reaches_everyone(self):
        bus = AgentBus()
        bus.send_to("alice", "x", {}, sender="host")
        bus.send_to("bob", "y", {}, sender="host")
        bus.broadcast("alert", {"level": "high"}, sender="host")

        assert len(bus.receive("alice")) == 2   # x + broadcast
        assert len(bus.receive("bob")) == 2     # y + broadcast

    def test_history_is_audit_trail(self):
        bus = AgentBus()
        m1 = bus.send_to("b", "one", {}, sender="a")
        m2 = bus.send_to("c", "two", {}, sender="a")
        assert bus.history == (m1, m2)
        assert len(bus) == 2
        assert bus.messages_from("a") == [m1, m2]
        assert bus.messages_to("b") == [m1]

    def test_subscribe_notifies(self):
        bus = AgentBus()
        received = []
        bus.subscribe("alert", lambda m: received.append(m))
        bus.broadcast("alert", {"level": "high"})
        assert len(received) == 1
        assert received[0].payload == {"level": "high"}

    def test_message_factory(self):
        m = AgentMessage.new("note", {"k": "v"}, sender="alice", recipient="bob")
        assert m.message_id.startswith("msg_")
        assert m.sender == "alice"
        assert m.recipient == "bob"
        assert m.kind == "note"

    def test_broadcast_constant(self):
        assert BROADCAST == "*"
