import React, { useEffect } from 'react';
import { ActivityIndicator, Platform, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { WebView } from 'react-native-webview';

const WEB_APP_URL = 'https://poenta.app/app/?native=android&exactWeb=1';

function LoadingView() {
  return (
    <View style={styles.loading}>
      <ActivityIndicator color="#f8d547" size="large" />
      <Text style={styles.loadingText}>טוען את Poenta…</Text>
    </View>
  );
}

function WebFallback() {
  useEffect(() => {
    if (typeof window !== 'undefined') window.location.replace(WEB_APP_URL);
  }, []);

  return <LoadingView />;
}

export default function App() {
  if (Platform.OS === 'web') return <WebFallback />;

  return (
    <View style={styles.container}>
      <StatusBar style="light" backgroundColor="#050505" />
      <WebView
        source={{ uri: WEB_APP_URL }}
        style={styles.webview}
        containerStyle={styles.webviewContainer}
        startInLoadingState
        renderLoading={() => <LoadingView />}
        javaScriptEnabled
        domStorageEnabled
        sharedCookiesEnabled
        thirdPartyCookiesEnabled
        allowsBackForwardNavigationGestures
        setSupportMultipleWindows={false}
        originWhitelist={['https://*']}
        pullToRefreshEnabled
        overScrollMode="never"
        cacheEnabled
        userAgent="PoentaApp/0.3.0 Android WebView"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050505',
  },
  webview: {
    flex: 1,
    backgroundColor: '#050505',
  },
  webviewContainer: {
    flex: 1,
    backgroundColor: '#050505',
  },
  loading: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    backgroundColor: '#050505',
  },
  loadingText: {
    color: '#f6f0dc',
    fontSize: 16,
    writingDirection: 'rtl',
  },
});
