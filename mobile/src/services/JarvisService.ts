/**
 * Jarvis WebSocket Servisi
 * Sunucuya bağlantı, ses gönderme, yanıt alma
 */

export type JarvisState = 'idle' | 'connecting' | 'listening' | 'transcribing' | 'thinking' | 'speaking' | 'error';

export interface JarvisMessage {
  type: 'status' | 'transcript' | 'response' | 'audio' | 'error';
  data: string;
}

type MessageHandler = (msg: JarvisMessage) => void;
type StateHandler = (state: JarvisState) => void;

class JarvisService {
  private ws: WebSocket | null = null;
  private serverUrl: string = 'ws://192.168.1.100:8765/ws'; // PC'nin IP'si
  private clientId: string = `mobile-${Math.random().toString(36).substr(2, 9)}`;
  private onMessage: MessageHandler | null = null;
  private onStateChange: StateHandler | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private isConnected: boolean = false;

  setServerUrl(url: string) {
    this.serverUrl = url;
  }

  setHandlers(onMessage: MessageHandler, onStateChange: StateHandler) {
    this.onMessage = onMessage;
    this.onStateChange = onStateChange;
  }

  async connect(): Promise<void> {
    const url = `${this.serverUrl}/${this.clientId}`;
    console.log('Jarvis sunucusuna bağlanıyor:', url);
    this._setState('connecting');

    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
          console.log('✅ Jarvis bağlantısı kuruldu');
          this.isConnected = true;
          this._setState('idle');
          resolve();
        };

        this.ws.onmessage = (event) => {
          try {
            const msg: JarvisMessage = JSON.parse(event.data);
            if (msg.type === 'status') {
              this._setState(msg.data as JarvisState);
            }
            this.onMessage?.(msg);
          } catch (e) {
            console.error('Mesaj ayrıştırma hatası:', e);
          }
        };

        this.ws.onerror = (error) => {
          console.error('WebSocket hatası:', error);
          this._setState('error');
          reject(error);
        };

        this.ws.onclose = () => {
          console.log('Bağlantı koptu, 3s sonra yeniden bağlanılıyor...');
          this.isConnected = false;
          this._setState('connecting');
          this.reconnectTimer = setTimeout(() => this.connect(), 3000);
        };

      } catch (e) {
        reject(e);
      }
    });
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.ws?.close();
    this.ws = null;
    this.isConnected = false;
  }

  async sendAudio(base64Audio: string): Promise<void> {
    this._send({ type: 'audio', data: base64Audio });
  }

  async sendText(text: string): Promise<void> {
    this._send({ type: 'text', data: text });
  }

  resetConversation() {
    this._send({ type: 'reset', data: '' });
  }

  private _send(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      console.warn('WebSocket bağlı değil, mesaj gönderilemedi');
    }
  }

  private _setState(state: JarvisState) {
    this.onStateChange?.(state);
  }

  get connected() {
    return this.isConnected;
  }
}

export default new JarvisService();
