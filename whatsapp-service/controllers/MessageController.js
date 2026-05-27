// controllers/MessageController.js
class MessageController {
  constructor(messenger, db) {
    this.messenger = messenger;
    this.db = db;
  }

  sendMessage = async (req, res) => {
    // Destructure is_group from the request body
    const { number, message, conversation_id, group_id } = req.body;

    try {
      let jid = group_id.includes("@") ? group_id : `${group_id}@g.us`;

      console.log(`Sending message to JID: ${jid}`);

      const result = await this.messenger.sendMessage(jid, message);
      if (!result.success) {
        throw new Error(result.error || "Unknown sending error");
      }

      await this.db.saveMessage({
        whatsapp_id: result.response.id.id,
        from_number: number,
        body: message,
        is_from_me: true,
        conversation_id: conversation_id,
        group_id: group_id ? jid : null,
      });

      res.json({ status: "sent" });
    } catch (error) {
      console.error("Error in sendMessage controller:", error);
      res.status(500).json({ error: "Failed to send message `{" + error + "}`" });
    }
  };

  getWebhooks = async (req, res) => {
    try {
      const webhooks = await this.db.getAllWebhooks();
      res.status(200).json(webhooks);
    } catch (error) {
      res.status(500).json({ error: "Failed to fetch webhooks" });
    }
  };

  registerWebhook = async (req, res) => {
    const { url, retries, secret } = req.body;
    if (!url) return res.status(400).json({ error: "Webhook URL is required" });

    try {
      const newWebhook = await this.db.insertWebhook({ url, retries, secret });
      res.status(201).json({
        message: "Webhook registered successfully",
        webhook: newWebhook,
      });
    } catch (error) {
      res.status(500).json({ error: "Failed to register webhook" });
    }
  };

  deleteWebhook = async (req, res) => {
    const { id } = req.params;
    try {
      const deletedWebhook = await this.db.deleteWebhook(id);
      if (!deletedWebhook)
        return res.status(404).json({ error: "Webhook not found" });
      res.status(200).json({
        message: "Webhook deleted successfully",
        deleted: deletedWebhook,
      });
    } catch (error) {
      res.status(500).json({ error: "Failed to delete webhook" });
    }
  };
}

module.exports = MessageController;
