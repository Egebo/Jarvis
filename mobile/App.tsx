/**
 * Jarvis Mobile — App Entry Point
 */

import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StatusBar } from 'react-native';
import MainScreen from './src/screens/MainScreen';
import SettingsScreen from './src/screens/SettingsScreen';

const Tab = createBottomTabNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <StatusBar barStyle="light-content" backgroundColor="#050A18" />
      <Tab.Navigator
        screenOptions={{
          headerShown: false,
          tabBarStyle: {
            backgroundColor: '#050A18',
            borderTopColor: '#00BFFF20',
          },
          tabBarActiveTintColor: '#00BFFF',
          tabBarInactiveTintColor: '#FFFFFF30',
          tabBarLabelStyle: {
            fontFamily: 'monospace',
            fontSize: 10,
            letterSpacing: 1,
          },
        }}
      >
        <Tab.Screen
          name="Jarvis"
          component={MainScreen}
          options={{ tabBarIcon: () => null }}
        />
        <Tab.Screen
          name="Ayarlar"
          component={SettingsScreen}
          options={{ tabBarIcon: () => null }}
        />
      </Tab.Navigator>
    </NavigationContainer>
  );
}
