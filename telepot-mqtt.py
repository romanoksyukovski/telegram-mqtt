import telepot
from telepot.delegate import per_chat_id, create_open, pave_event_space
import time
import sys
import paho.mqtt.client as mqtt

class TelepotMQTTClient(mqtt.Client):
	def __init__(self, bot):
		super(TelepotMQTTClient, self).__init__()
		self.bot = bot
		self.chat_id = None
		self.is_mqtt_connected = False
		self.on_connect = self.mqtt_on_connect
		self.on_disconnect = self.mqtt_on_disconnect
		self.on_message = self.mqtt_on_message
		self.on_subscribe = self.mqtt_on_subscribe
		self.on_unsubscribe = self.mqtt_on_unsubscribe

	def __del__(self):
		self.disconnect()
		super(TelepotMQTTClient, self).__del__()

	def connect(self, chat_id, *args, **kwargs):
		self.chat_id = chat_id
		super(TelepotMQTTClient, self).connect(*args, **kwargs)

	def mqtt_on_connect(self, client, userdata, flags, rc):
		self.is_mqtt_connected = True
		self.bot.sendMessage(self.chat_id, "Successfully conected to mqtt broker ({0})".format(str(rc)))
		return

	def mqtt_on_disconnect(self, client, userdata, rc):
		if rc != 0:
			self.bot.sendMessage(self.chat_id, "Unexpected disconnect ({0})".format(str(rc)))
		self.is_mqtt_connected = False
		self.bot.sendMessage(self.chat_id, "Successfully disconnected from mqtt broker ({0})".format(str(rc)))
		return

	def mqtt_on_subscribe(self, client, userdata, mid, granted_qos):
		self.bot.sendMessage(self.chat_id, "Successfully subscribed to topic ({0})".format(mid))

	def mqtt_on_unsubscribe(self, userdata, mid, granted_qos):
		self.bot.sendMessage(self.chat_id, "Successfully unsubscribed from topic ({0})".format(mid))

	def mqtt_on_message(self, client, userdata, msg):
		self.bot.sendMessage(self.chat_id, "Topic {0} message recieved: {1}".format(msg.topic, msg.payload))

class ValidationException(Exception):
	pass

class MQTTDelegatorBot(telepot.DelegatorBot):
	def __init__(self, *args, **kwargs):
		self.mqtt_sessions = []
		super(MQTTDelegatorBot, self).__init__(*args, **kwargs)

	def start_new_session(self, chat_id):
		new_client = TelepotMQTTClient(self)
		self.mqtt_sessions.append({"chat_id": chat_id, "mqtt_client": new_client});
		return new_client

	def get_mqqt_client_by_chat_id(self, chat_id):
		for session in self.mqtt_sessions:
			if session["chat_id"] == chat_id:
				return session["mqtt_client"]
		return				


class MQTTChatHandler(telepot.helper.ChatHandler):
	def __init__(self, *args, **kwargs):
		super(MQTTChatHandler, self).__init__(*args, **kwargs)
		self._chat_mqtt_topics = []
		self.supported_commands = ['connect', 'disconnect', 'isconnected', 'subscribe', 'unsubscribe', 'publish']

	def validate_msg_command(self, msg):
		flavor = telepot.flavor(msg)
		summary = telepot.glance(msg, flavor=flavor)
		msg_content_type, msg_chat_type, msg_chat_id = summary

		# checking if this is a chat
		if flavor != "chat":
			raise ValidationException("Sorry, I process messages only in chats")

		# checking that the message is text and is private chat
		if msg_content_type != "text" or msg_chat_type != "private":
			raise ValidationException("Sorry, but I react only on text commands in private chat ...")

		# parsing the message
		cmd_pretty = [c for c in msg["text"].split(" ") if c != ""]
		cmd = cmd_pretty[0]

		# checking that the message starts with "/"
		if cmd[0] != "/":
			raise ValidationException("Sorry, but a proper command should start with / symbol")

		# checking that the command is supported
		if cmd[1:] not in self.supported_commands:
			raise ValidationException("Command {0} is not supported. These are the supported commands: {1}".format(cmd, ", ".join(["/" + c for c in self.supported_commands])))

		# parsing params
		cmd_params = {}
		for s in cmd_pretty[1:]:
			if len(s.split("=")) == 2:
				cmd_params[s.split("=")[0]]=s.split("=")[1]
			else:
				raise ValidationException("One of the params is provided in the incorrect way. Every param should be {param_name}={param_value}")

		return cmd[1:], cmd_params

	def on_chat_message(self, msg):
		"""
		connect - connects to a mqqt broker. Two parameters are expected: "host" and "port". Example: /connect host=test.mosquitto.org port=1883
		subscribe - subscribes to a mqtt topic. "Topic" parameter is expected. Example: /subscribe topic=telegram/test01
		unsubscribe - unsubscribes from a mqtt topic. "Topic" parameter is expected. Example: /unsubscribe topic=telegram/test01
		publish - publishes a mqtt message. Two parameters are expected: "topic" and "payload". Example: /publish topic=telegram/test01 payload=hello
		isconnected - checks if you are connected to a mqtt broker. No parameters are expected. Example: /isconnected
		disconnect - disconnects you from a mqtt broker. No parameters are expected. Example: /disconnect
		"""
		try:
			# search for session
			mqtt_client = self.bot.get_mqqt_client_by_chat_id(msg["chat"]["id"])
			if mqtt_client == None:
				mqtt_client = self.bot.start_new_session(msg["chat"]["id"])

			cmd, cmd_params = self.validate_msg_command(msg);
			if cmd == "connect":
				if "host" in cmd_params.keys() and "port" in cmd_params.keys():
					self.sender.sendMessage("You requested to connect to '{0}:{1}'".format(cmd_params["host"], cmd_params["port"]))
					
					# initializing mqtt client
					if not mqtt_client.is_mqtt_connected:
						mqtt_client.connect(chat_id=msg["chat"]["id"], host=cmd_params["host"], port=int(cmd_params["port"]))
						mqtt_client.loop_start()
					else:
						self.sender.sendMessage("You are already connected")
						return
				else:
					raise ValidationException("Sorry, but connect command should have both host and port params")
			
			if cmd == "disconnect":
				self.sender.sendMessage("You requested to disconnect from mqtt broker")
				mqtt_client.loop_stop()
				mqtt_client.disconnect()
				return

			if cmd == "isconnected":
				if (mqtt_client != None) and mqtt_client.is_mqtt_connected:
					self.sender.sendMessage("Yes, you are connected to a mqtt broker.")
				else:
					self.sender.sendMessage("No, you are not connected to a mqtt broker.")
				return
			
			if cmd == "subscribe":
				if "topic" in cmd_params.keys():
					self.sender.sendMessage("You asked to subscribe to {0} topic.".format(cmd_params["topic"]))
					if mqtt_client.is_mqtt_connected:
						mqtt_client.subscribe(cmd_params["topic"])
					else:
						raise ValidationException("You are not connected to mqtt")
					return
				else:
					raise ValidationException("Sorry, but subscribe command should have a topic param specified")

			if cmd == "unsubscribe":
				if "topic" in cmd_params.keys():
					self.sender.sendMessage("You asked to unsubscribe from {0} topic.".format(cmd_params["topic"]))
					if mqtt_client.is_mqtt_connected:
						mqtt_client.unsubscribe(cmd_params["topic"].encode('ascii','ignore'))
					return
				else:
					raise ValidationException("Sorry, but unsubscribe command should have a topic param specified")

			if cmd == "publish":
				if "topic" in cmd_params.keys() and "payload" in cmd_params.keys():
					self.sender.sendMessage("You asked to publish a message to {0} topic with payload {1}.".format(cmd_params["topic"], cmd_params["payload"]))
					if mqtt_client.is_mqtt_connected:
						mqtt_client.publish(cmd_params["topic"], cmd_params["payload"])
					return
				else:
					raise ValidationException("Sorry, but publish command should have a topic and payload params specified")

		except ValidationException as e:
			self.sender.sendMessage(e.message)
			return

TOKEN = sys.argv[1]

bot = MQTTDelegatorBot(TOKEN, [
    pave_event_space()(
        per_chat_id(), create_open, MQTTChatHandler, timeout=10
        ),
])

bot.message_loop(run_forever='Listening ...')