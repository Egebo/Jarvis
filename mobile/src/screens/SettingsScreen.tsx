/**
 * Ayarlar Ekranı — Sunucu IP, ses ayarları
 */

import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Switch,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import JarvisService from '../services/JarvisService';

export default function SettingsScreen() {
  const [serverIp, setServerIp] = useState('192.168.1.100');
  const [port, setPort] = useState('8765');
  const [useElevenLabs, setUseElevenLabs] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    AsyncStorage.multiGet(['serverIp', 'port', 'useElevenLabs']).then(values => {
      const ip = values.find(v => v[0] === 'serverIp')?.[1];
      const p = values.find(v => v[0] === 'port')?.[1];
      if (ip) setServerIp(ip);
      if (p) setPort(p);
    });
  }, []);

  const save = async () => {
    await AsyncStorage.multiSet([
      ['serverIp', serverIp],
      ['port', port],
      ['useElevenLabs', String(useElevenLabs)],
    ]);
    JarvisService.setServerUrl(`ws://${serverIp}:${port}/ws`);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>AYARLAR</Text>

      <View style={styles.section}>
        <Text style={styles.label}>SUNUCU IP (PC'nin yerel IP'si)</Text>
        <TextInput
          style={styles.input}
          value={serverIp}
          onChangeText={setServerIp}
          placeholder="192.168.1.100"
          placeholderTextColor="#FFFFFF20"
          keyboardType="numeric"
        />
        <Text style={styles.hint}>
          PC'de: ipconfig (Windows) veya ifconfig (Mac/Linux)
        </Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.label}>PORT</Text>
        <TextInput
          style={styles.input}
          value={port}
          onChangeText={setPort}
          placeholder="8765"
          placeholderTextColor="#FFFFFF20"
          keyboardType="numeric"
        />
      </View>

      <View style={styles.section}>
        <View style={styles.row}>
          <Text style={styles.label}>ElevenLabs TTS (Yüksek Kalite)</Text>
          <Switch
            value={useElevenLabs}
            onValueChange={setUseElevenLabs}
            thumbColor={useElevenLabs ? '#00BFFF' : '#333'}
            trackColor={{ false: '#1a1a2e', true: '#00BFFF40' }}
          />
        </View>
        {useElevenLabs && (
          <Text style={styles.hint}>
            API anahtarını backend/.env dosyasına ekleyin
          </Text>
        )}
      </View>

      <TouchableOpacity style={styles.saveButton} onPress={save}>
        <Text style={styles.saveText}>{saved ? '✅ KAYDEDİLDİ' : 'KAYDET'}</Text>
      </TouchableOpacity>

      <View style={styles.infoBox}>
        <Text style={styles.infoTitle}>Bağlantı Adresi:</Text>
        <Text style={styles.infoText}>ws://{serverIp}:{port}/ws</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050A18',
    padding: 24,
    paddingTop: 60,
  },
  title: {
    fontSize: 20,
    fontWeight: '900',
    color: '#00BFFF',
    letterSpacing: 6,
    fontFamily: 'monospace',
    marginBottom: 32,
  },
  section: {
    marginBottom: 24,
  },
  label: {
    fontSize: 10,
    color: '#00BFFF80',
    letterSpacing: 2,
    fontFamily: 'monospace',
    marginBottom: 8,
  },
  input: {
    borderWidth: 1,
    borderColor: '#00BFFF30',
    borderRadius: 6,
    padding: 12,
    color: '#E0F0FF',
    fontSize: 16,
    fontFamily: 'monospace',
    backgroundColor: '#001020',
  },
  hint: {
    fontSize: 11,
    color: '#FFFFFF30',
    marginTop: 6,
    fontFamily: 'monospace',
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  saveButton: {
    borderWidth: 1,
    borderColor: '#00BFFF',
    borderRadius: 6,
    padding: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  saveText: {
    color: '#00BFFF',
    fontSize: 13,
    fontWeight: 'bold',
    letterSpacing: 3,
    fontFamily: 'monospace',
  },
  infoBox: {
    marginTop: 32,
    padding: 16,
    borderRadius: 6,
    backgroundColor: '#001020',
    borderWidth: 1,
    borderColor: '#FFFFFF10',
  },
  infoTitle: {
    color: '#FFFFFF40',
    fontSize: 10,
    letterSpacing: 2,
    fontFamily: 'monospace',
    marginBottom: 6,
  },
  infoText: {
    color: '#00BFFF',
    fontFamily: 'monospace',
    fontSize: 14,
  },
});
