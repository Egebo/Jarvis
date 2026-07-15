/**
 * Jarvis Ana Ekranı
 * Iron Man HUD'una benzer koyu, mavi-tonlu arayüz
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
  Animated,
  Dimensions,
  Alert,
  Platform,
} from 'react-native';
import AudioRecorderPlayer from 'react-native-audio-recorder-player';
import { PERMISSIONS, request, RESULTS } from 'react-native-permissions';
import JarvisService, { JarvisState, JarvisMessage } from '../services/JarvisService';

const { width, height } = Dimensions.get('window');

interface ChatMessage {
  id: string;
  role: 'user' | 'jarvis';
  text: string;
  timestamp: Date;
}

const STATE_LABELS: Record<JarvisState, string> = {
  idle: 'HAZIR',
  connecting: 'BAĞLANIYOR',
  listening: 'DİNLİYORUM',
  transcribing: 'ANLIYORUM',
  thinking: 'DÜŞÜNÜYORUM',
  speaking: 'KONUŞUYORUM',
  error: 'HATA',
};

const STATE_COLORS: Record<JarvisState, string> = {
  idle: '#00BFFF',
  connecting: '#FFD700',
  listening: '#00FF7F',
  transcribing: '#00BFFF',
  thinking: '#FF6B6B',
  speaking: '#9B59B6',
  error: '#FF4444',
};

export default function MainScreen() {
  const [state, setState] = useState<JarvisState>('connecting');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [serverUrl, setServerUrl] = useState('ws://192.168.1.100:8765/ws');

  const audioPlayer = useRef(new AudioRecorderPlayer());
  const pulseAnim = useRef(new Animated.Value(1)).current;
  const scrollRef = useRef<ScrollView>(null);

  // ─── Başlangıç ─────────────────────────────────────────────────────────
  useEffect(() => {
    requestPermissions().then(() => {
      connectToServer();
    });

    return () => {
      JarvisService.disconnect();
    };
  }, []);

  // ─── Pulse animasyonu ───────────────────────────────────────────────────
  useEffect(() => {
    if (state === 'listening') {
      Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 1.3, duration: 500, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1, duration: 500, useNativeDriver: true }),
        ])
      ).start();
    } else {
      pulseAnim.setValue(1);
    }
  }, [state]);

  // ─── İzinler ────────────────────────────────────────────────────────────
  const requestPermissions = async () => {
    const perm = Platform.OS === 'ios' ? PERMISSIONS.IOS.MICROPHONE : PERMISSIONS.ANDROID.RECORD_AUDIO;
    const result = await request(perm);
    if (result !== RESULTS.GRANTED) {
      Alert.alert('İzin Gerekli', 'Mikrofon izni olmadan Jarvis kullanılamaz.');
    }
  };

  // ─── Sunucu Bağlantısı ──────────────────────────────────────────────────
  const connectToServer = useCallback(async () => {
    JarvisService.setServerUrl(serverUrl);
    JarvisService.setHandlers(handleMessage, setState);
    try {
      await JarvisService.connect();
    } catch (e) {
      console.error('Bağlantı hatası:', e);
    }
  }, [serverUrl]);

  // ─── Sunucu Mesajları ───────────────────────────────────────────────────
  const handleMessage = useCallback((msg: JarvisMessage) => {
    if (msg.type === 'transcript') {
      addMessage('user', msg.data);
    } else if (msg.type === 'response') {
      addMessage('jarvis', msg.data);
    } else if (msg.type === 'audio') {
      playAudioFromBase64(msg.data);
    }
  }, []);

  const addMessage = (role: 'user' | 'jarvis', text: string) => {
    setMessages(prev => [...prev, {
      id: Date.now().toString(),
      role,
      text,
      timestamp: new Date(),
    }]);
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
  };

  // ─── Ses Kayıt ──────────────────────────────────────────────────────────
  const startRecording = async () => {
    if (state !== 'idle') return;
    setIsRecording(true);

    const path = Platform.OS === 'android'
      ? '/sdcard/jarvis_rec.wav'
      : 'jarvis_rec.wav';

    await audioPlayer.current.startRecorder(path, {
      SampleRate: 16000,
      Channels: 1,
      AudioEncoderAndroid: 3, // AAC_ELD
    });
  };

  const stopRecording = async () => {
    if (!isRecording) return;
    setIsRecording(false);

    const filePath = await audioPlayer.current.stopRecorder();

    // Dosyayı base64'e çevir ve gönder
    const RNFS = await import('@react-native-async-storage/async-storage');
    // Not: gerçek uygulamada react-native-fs kullan
    // Şimdilik placeholder
    console.log('Kayıt tamamlandı:', filePath);
    // JarvisService.sendAudio(base64Audio);
  };

  // ─── Ses Çalma ──────────────────────────────────────────────────────────
  const playAudioFromBase64 = async (base64: string) => {
    try {
      // Base64'ü geçici dosyaya yaz ve çal
      const path = Platform.OS === 'android'
        ? '/sdcard/jarvis_response.wav'
        : 'jarvis_response.wav';
      await audioPlayer.current.startPlayer(path);
    } catch (e) {
      console.error('Ses çalma hatası:', e);
    }
  };

  // ─── Render ─────────────────────────────────────────────────────────────
  const stateColor = STATE_COLORS[state];

  return (
    <View style={styles.container}>
      {/* Header — HUD tarzı */}
      <View style={styles.header}>
        <Text style={styles.title}>J.A.R.V.I.S</Text>
        <Text style={styles.subtitle}>Just A Rather Very Intelligent System</Text>
        <View style={[styles.statusDot, { backgroundColor: stateColor }]} />
        <Text style={[styles.statusText, { color: stateColor }]}>
          {STATE_LABELS[state]}
        </Text>
      </View>

      {/* Chat Alanı */}
      <ScrollView
        ref={scrollRef}
        style={styles.chatArea}
        contentContainerStyle={styles.chatContent}
      >
        {messages.length === 0 && (
          <Text style={styles.emptyText}>
            Merhaba Egemen. Nasıl yardımcı olabilirim?
          </Text>
        )}
        {messages.map(msg => (
          <View
            key={msg.id}
            style={[
              styles.bubble,
              msg.role === 'user' ? styles.userBubble : styles.jarvisBubble
            ]}
          >
            <Text style={styles.bubbleLabel}>
              {msg.role === 'user' ? 'SİZ' : 'JARVIS'}
            </Text>
            <Text style={styles.bubbleText}>{msg.text}</Text>
          </View>
        ))}
      </ScrollView>

      {/* Kontroller */}
      <View style={styles.controls}>
        {/* Ana Mikrofon Butonu */}
        <TouchableOpacity
          onPressIn={startRecording}
          onPressOut={stopRecording}
          activeOpacity={0.8}
        >
          <Animated.View
            style={[
              styles.micButton,
              { borderColor: stateColor },
              isRecording && { transform: [{ scale: pulseAnim }] }
            ]}
          >
            <Text style={[styles.micIcon, { color: stateColor }]}>
              {isRecording ? '⏹' : '🎙'}
            </Text>
          </Animated.View>
        </TouchableOpacity>

        <Text style={styles.micHint}>
          {isRecording ? 'Bırakın' : 'Basılı tutun'}
        </Text>

        {/* Sıfırla */}
        <TouchableOpacity
          style={styles.resetButton}
          onPress={() => {
            JarvisService.resetConversation();
            setMessages([]);
          }}
        >
          <Text style={styles.resetText}>↺ Sıfırla</Text>
        </TouchableOpacity>
      </View>

      {/* Dekoratif HUD çizgileri */}
      <View style={[styles.hudLine, { top: height * 0.25, borderColor: stateColor + '40' }]} />
      <View style={[styles.hudLine, { bottom: height * 0.2, borderColor: stateColor + '40' }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050A18',
  },
  header: {
    alignItems: 'center',
    paddingTop: 60,
    paddingBottom: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#00BFFF30',
  },
  title: {
    fontSize: 32,
    fontWeight: '900',
    color: '#00BFFF',
    letterSpacing: 8,
    fontFamily: 'monospace',
  },
  subtitle: {
    fontSize: 10,
    color: '#00BFFF60',
    letterSpacing: 2,
    marginTop: 4,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 12,
  },
  statusText: {
    fontSize: 11,
    letterSpacing: 3,
    fontFamily: 'monospace',
    marginTop: 4,
  },
  chatArea: {
    flex: 1,
    paddingHorizontal: 16,
  },
  chatContent: {
    paddingVertical: 20,
    gap: 12,
  },
  emptyText: {
    color: '#00BFFF40',
    textAlign: 'center',
    fontFamily: 'monospace',
    fontSize: 14,
    marginTop: 40,
    fontStyle: 'italic',
  },
  bubble: {
    borderRadius: 8,
    padding: 14,
    maxWidth: '90%',
    borderWidth: 1,
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#001830',
    borderColor: '#00BFFF40',
  },
  jarvisBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#0D0D2B',
    borderColor: '#9B59B640',
  },
  bubbleLabel: {
    fontSize: 9,
    letterSpacing: 2,
    color: '#FFFFFF40',
    marginBottom: 6,
    fontFamily: 'monospace',
  },
  bubbleText: {
    fontSize: 15,
    color: '#E0F0FF',
    lineHeight: 22,
  },
  controls: {
    alignItems: 'center',
    paddingBottom: 40,
    paddingTop: 20,
    gap: 12,
  },
  micButton: {
    width: 90,
    height: 90,
    borderRadius: 45,
    borderWidth: 2,
    backgroundColor: '#00BFFF10',
    justifyContent: 'center',
    alignItems: 'center',
  },
  micIcon: {
    fontSize: 36,
  },
  micHint: {
    color: '#FFFFFF30',
    fontSize: 11,
    letterSpacing: 2,
    fontFamily: 'monospace',
  },
  resetButton: {
    paddingHorizontal: 20,
    paddingVertical: 8,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: '#FFFFFF20',
  },
  resetText: {
    color: '#FFFFFF40',
    fontSize: 12,
    fontFamily: 'monospace',
  },
  hudLine: {
    position: 'absolute',
    left: 20,
    right: 20,
    height: 1,
    borderTopWidth: 1,
  },
});
