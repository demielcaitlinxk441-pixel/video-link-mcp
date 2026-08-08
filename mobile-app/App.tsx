import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AppState,
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as FileSystem from 'expo-file-system/legacy';
import * as Clipboard from 'expo-clipboard';
import * as SecureStore from 'expo-secure-store';
import * as Sharing from 'expo-sharing';
import * as SQLite from 'expo-sqlite';
import { Ionicons } from '@expo/vector-icons';
import { requireNativeModule } from 'expo-modules-core';

type Tab = 'home' | 'assistant' | 'settings';
type DownloadRow = {
  id: number;
  title: string;
  url: string;
  local_uri: string;
  status: string;
  created_at: string;
  in_knowledge: number;
  category: string | null;
};
type AIConfig = {
  baseUrl: string;
  apiKey: string;
  model: string;
  temperature: string;
};
type AIResult = { summary: string; category: string; tags: string[] };
type ChatMessage = { id: number; role: 'user' | 'assistant'; content: string };
type TermuxBridgeAPI = {
  isInstalled(): Promise<boolean>;
  runYtDlp(url: string, outputDir?: string, downloadId?: string): Promise<string>;
  runDouyin(url: string, outputDir?: string): Promise<string>;
  authorizeYuanbao(): Promise<string>;
  runWechatChannels(url: string, cookie: string, outputDir?: string): Promise<string>;
  deleteFile(path: string): Promise<boolean>;
  openVideo(path: string): Promise<boolean>;
  shareVideoToWechat?(path: string): Promise<boolean>;
  openTermux(): Promise<boolean>;
  cancelYtDlp?(downloadId: string): Promise<boolean>;
  addListener?(eventName: string, listener: (event: { id: string; progress: number }) => void): { remove: () => void };
};

const COLORS = {
  ink: '#102A43',
  muted: '#627D98',
  faint: '#F3F7FB',
  line: '#D9E6F2',
  cyan: '#0E7490',
  cyanDark: '#155E75',
  cyanTint: '#E7F7FA',
  white: '#FFFFFF',
  success: '#16805B',
  danger: '#B42318',
};
const DB_NAME = 'videolink-mobile.db';
const CONFIG_KEY = 'videolink.ai.config';
const DEFAULT_CONFIG: AIConfig = {
  baseUrl: 'https://api.openai.com/v1',
  apiKey: '',
  model: 'gpt-4o-mini',
  temperature: '0.2',
};
// The bridge is optional at startup. Older installs or a build without the
// native module must still be able to open the app and use direct downloads.
let TermuxBridge: TermuxBridgeAPI | null = null;
if (Platform.OS === 'android') {
  try {
    TermuxBridge = requireNativeModule<TermuxBridgeAPI>('TermuxBridge');
  } catch {
    TermuxBridge = null;
  }
}

const db = SQLite.openDatabaseSync(DB_NAME);
db.execSync(`
  PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    local_uri TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    in_knowledge INTEGER NOT NULL DEFAULT 0,
    category TEXT
  );
  CREATE TABLE IF NOT EXISTS knowledge_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    download_id INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '未分类',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY(download_id) REFERENCES downloads(id) ON DELETE CASCADE
  );
  CREATE TABLE IF NOT EXISTS assistant_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
  );
`);

function normalizeBaseUrl(value: string) {
  const trimmed = value.trim().replace(/\/+$/, '');
  return trimmed.endsWith('/v1') ? trimmed : `${trimmed}/v1`;
}

function titleFromUrl(value: string) {
  try {
    const parsed = new URL(value);
    const last = parsed.pathname.split('/').filter(Boolean).pop();
    return decodeURIComponent(last || parsed.hostname).replace(/\.[a-z0-9]{2,5}$/i, '').slice(0, 80);
  } catch {
    return '手机视频';
  }
}

function extractHttpUrl(value: string) {
  const match = value.match(/https?:\/\/[^\s]+/i);
  return match ? match[0].replace(/[，。！？、）》】\]}>"']+$/g, '') : '';
}

const EXTERNAL_DOWNLOAD_DIR = 'file:///sdcard/Download/VideoLink/';
function normalizeLocalUri(value: string) {
  if (/^file:\/\//i.test(value)) {
    try { return decodeURI(value); } catch { return value; }
  }
  if (/^content:\/\//i.test(value)) return value;
  return value.startsWith('/') ? `file://${value}` : value;
}
function titleFromFileName(value: string) {
  return decodeURIComponent(value).replace(/\.[^.]+$/, '').slice(0, 80) || '手机视频';
}
async function syncExternalDownloads() {
  if (Platform.OS !== 'android') return;
  try {
    const names = await FileSystem.readDirectoryAsync(EXTERNAL_DOWNLOAD_DIR);
    for (const name of names.filter((item) => /\.(mp4|m4v|webm|mov|mkv)$/i.test(item))) {
      const localUri = `${EXTERNAL_DOWNLOAD_DIR}${encodeURIComponent(name)}`;
      const existing = db.getAllSync<{ id: number }>('SELECT id FROM downloads WHERE local_uri = ?', localUri);
      if (!existing.length) {
        db.runSync('INSERT INTO downloads (title, url, local_uri, status, created_at) VALUES (?, ?, ?, ?, ?)', titleFromFileName(name), localUri, localUri, 'completed', new Date().toISOString());
      }
    }
  } catch {
    // The folder may not exist yet or may be inaccessible on older Android versions.
  }
}

async function loadConfig(): Promise<AIConfig> {
  try {
    const raw = await SecureStore.getItemAsync(CONFIG_KEY);
    return raw ? { ...DEFAULT_CONFIG, ...JSON.parse(raw) } : DEFAULT_CONFIG;
  } catch {
    return DEFAULT_CONFIG;
  }
}

async function saveConfig(config: AIConfig) {
  await SecureStore.setItemAsync(CONFIG_KEY, JSON.stringify({ ...config, baseUrl: normalizeBaseUrl(config.baseUrl) }));
}

function rows(): DownloadRow[] {
  return db.getAllSync<DownloadRow>(
    'SELECT id, title, url, local_uri, status, created_at, in_knowledge, category FROM downloads ORDER BY id DESC',
  );
}
function hasExistingDownload(url: string) {
  return db.getAllSync<{ id: number }>('SELECT id FROM downloads WHERE url = ? AND status = ? LIMIT 1', url, 'completed').length > 0;
}
function chatRows(): ChatMessage[] {
  return db.getAllSync<ChatMessage>(
    'SELECT id, role, content FROM (SELECT id, role, content FROM assistant_messages ORDER BY id DESC LIMIT 50) ORDER BY id ASC',
  );
}

function knowledgeContext(query: string) {
  const needle = `%${query.trim()}%`;
  const items = db.getAllSync<{ title: string; summary: string; category: string; tags: string }>(
    'SELECT title, summary, category, tags FROM knowledge_items WHERE title LIKE ? OR summary LIKE ? OR category LIKE ? OR tags LIKE ? ORDER BY id DESC LIMIT 12',
    needle,
    needle,
    needle,
    needle,
  );
  return items.length ? items : db.getAllSync<{ title: string; summary: string; category: string; tags: string }>('SELECT title, summary, category, tags FROM knowledge_items ORDER BY id DESC LIMIT 12');
}

async function askModel(config: AIConfig, messages: Array<{ role: string; content: string }>) {
  if (!config.apiKey.trim()) throw new Error('请先在“设置 → AI 配置”中填写 API Key。');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(`${normalizeBaseUrl(config.baseUrl)}/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${config.apiKey.trim()}` },
      body: JSON.stringify({ model: config.model.trim(), temperature: Number(config.temperature) || 0.2, messages }),
      signal: controller.signal,
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.error?.message || `AI 服务返回 ${response.status}`);
    return String(body?.choices?.[0]?.message?.content || '').trim();
  } finally {
    clearTimeout(timer);
  }
}

async function enrichWithAI(config: AIConfig, row: DownloadRow): Promise<AIResult | null> {
  if (!config.apiKey.trim()) return null;
  try {
    const raw = await askModel(config, [
      { role: 'system', content: '你是视频知识库整理助手。只输出 JSON：{"summary":"一句中文摘要","category":"一个分类","tags":["标签1","标签2"]}。不能确认内容时根据标题保守推断。' },
      { role: 'user', content: `请整理这个视频：${row.title}` },
    ]);
    const json = raw.match(/\{[\s\S]*\}/)?.[0];
    if (!json) return null;
    const parsed = JSON.parse(json) as Partial<AIResult>;
    return { summary: String(parsed.summary || ''), category: String(parsed.category || '未分类'), tags: Array.isArray(parsed.tags) ? parsed.tags.map(String).slice(0, 8) : [] };
  } catch {
    return null;
  }
}

export default function App() {
  const [tab, setTab] = useState<Tab>('home');
  const [appActive, setAppActive] = useState(AppState.currentState === 'active');
  const [downloads, setDownloads] = useState<DownloadRow[]>([]);
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<AIConfig>(DEFAULT_CONFIG);
  const [question, setQuestion] = useState('');
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [asking, setAsking] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [yuanbaoAuthorized, setYuanbaoAuthorized] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null);
  const [downloadMode, setDownloadMode] = useState<'yt-dlp' | 'wechat' | null>(null);
  const lastClipboardLinkRef = useRef('');
  const nativeDownloadIdRef = useRef<string | null>(null);
  const cancelRequestedRef = useRef(false);
  const refresh = useCallback(() => setDownloads(rows()), []);
  useEffect(() => {
    refresh();
    syncExternalDownloads().then(refresh);
    loadConfig().then(setConfig);
    setChatHistory(chatRows());
    SecureStore.getItemAsync('videolink.yuanbao.cookie').then((cookie) => setYuanbaoAuthorized(Boolean(cookie?.trim())));
  }, [refresh]);
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => setAppActive(nextState === 'active'));
    return () => subscription.remove();
  }, []);
  useEffect(() => {
    if (!TermuxBridge?.addListener) return;
    const subscription = TermuxBridge.addListener('downloadProgress', (event) => {
      if (event.id === nativeDownloadIdRef.current) setDownloadProgress(Math.max(0, Math.min(100, event.progress)));
    });
    return () => subscription?.remove();
  }, []);

  const completed = useMemo(() => downloads.filter((item) => item.status === 'completed'), [downloads]);
  const categorized = useMemo(() => completed.filter((item) => item.in_knowledge).length, [completed]);

  const termuxDownload = async (inputUrl = url) => {
    const link = extractHttpUrl(inputUrl);
    if (!link) {
      Alert.alert('链接不完整', '请先粘贴分享链接。');
      return;
    }
    if (!TermuxBridge) {
      Alert.alert('仅支持 Android', '内置平台解析引擎目前只支持 Android，iPhone 请使用电脑端或网页端。');
      return;
    }
    const isWechat = /(?:weixin\.qq\.com\/sph\/|channels\.weixin\.qq\.com\/(?:finder-preview|web\/pages\/feed))/i.test(link);
    const isDouyin = /(?:v\.douyin\.com|douyin\.com|iesdouyin\.com)/i.test(link);
    if (hasExistingDownload(link)) {
      Alert.alert('已经下载过', '最近下载里已经有这个链接，无需重复下载。');
      return;
    }
    setBusy(true);
    setDownloadMode(isWechat ? 'wechat' : 'yt-dlp');
    setDownloadProgress(isWechat ? null : 0);
    cancelRequestedRef.current = false;
    try {
      if (!(await TermuxBridge.isInstalled())) {
        Alert.alert('下载引擎不可用', '请重新安装最新版 APK。');
        return;
      }
      let localUri: string;
      if (isWechat) {
        const cookie = await SecureStore.getItemAsync('videolink.yuanbao.cookie');
        if (!cookie) {
          setTab('settings');
          Alert.alert('需要视频号授权', '请先在“设置”中点击“元宝授权”，登录后再下载。');
          return;
        }
        localUri = await TermuxBridge.runWechatChannels(link, cookie, '/sdcard/Download/VideoLink');
      } else if (isDouyin) {
        localUri = await TermuxBridge.runDouyin(link, '/sdcard/Download/VideoLink');
      } else {
        const downloadId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
        nativeDownloadIdRef.current = downloadId;
        localUri = await TermuxBridge.runYtDlp(link, '/sdcard/Download/VideoLink', downloadId);
      }
      db.runSync('INSERT INTO downloads (title, url, local_uri, status, created_at) VALUES (?, ?, ?, ?, ?)', titleFromUrl(link), link, normalizeLocalUri(localUri), 'completed', new Date().toISOString());
      setUrl('');
      refresh();
      Alert.alert('下载完成', '视频已保存，并已出现在“最近”列表。');
    } catch (error) {
      if (cancelRequestedRef.current) Alert.alert('已取消', '下载已取消，未保存不完整的视频。');
      else {
        const message = error instanceof Error ? error.message : '请检查网络后重试。';
        if (isWechat && /HTTP\s+(401|403|412)|授权|cookie|登录/i.test(message)) {
          await SecureStore.deleteItemAsync('videolink.yuanbao.cookie');
          setYuanbaoAuthorized(false);
          setTab('settings');
          Alert.alert('元宝授权已失效', '请重新完成元宝授权后再下载视频号内容。');
        } else Alert.alert('下载失败', message);
      }
    } finally {
      nativeDownloadIdRef.current = null;
      setDownloadMode(null);
      setDownloadProgress(null);
      setBusy(false);
    }
  };

  const cancelActiveDownload = async () => {
    if (!busy) return;
    cancelRequestedRef.current = true;
    try {
      if (downloadMode === 'yt-dlp' && nativeDownloadIdRef.current && TermuxBridge?.cancelYtDlp) await TermuxBridge.cancelYtDlp(nativeDownloadIdRef.current);
    } catch {
      // The download's finally block will restore the idle state.
    }
  };

  const authorizeWechat = async () => {
    if (!TermuxBridge) {
      Alert.alert('仅支持 Android', '视频号授权目前只支持 Android。');
      return;
    }
    try {
      const cookie = await TermuxBridge.authorizeYuanbao();
      if (!cookie.trim()) throw new Error('没有检测到有效的元宝登录凭据。');
      await SecureStore.setItemAsync('videolink.yuanbao.cookie', cookie);
      setYuanbaoAuthorized(true);
      Alert.alert('授权成功', '以后可以直接下载微信视频号链接。');
    } catch (error) {
      Alert.alert('授权失败', error instanceof Error ? error.message : '请完成元宝登录后重试。');
    }
  };

  const downloadUnified = async (inputUrl?: string) => {
    const link = extractHttpUrl(typeof inputUrl === 'string' ? inputUrl : url);
    if (!link) {
      Alert.alert('链接不完整', '请先粘贴视频链接。');
      return;
    }
    return termuxDownload(link);
  };

  useEffect(() => {
    if (tab !== 'home' || busy) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      Clipboard.getStringAsync().then((clipboardText) => {
        if (cancelled) return;
        const link = extractHttpUrl(clipboardText);
        const looksLikeVideo = /\.(?:mp4|m4v|webm|mov|mkv)(?:\?|$)/i.test(link) || /(?:b23\.tv|bilibili\.com|youtube\.com|youtu\.be|xhslink\.cn|xiaohongshu\.com|weixin\.qq\.com|channels\.weixin\.qq\.com|v\.douyin\.com|douyin\.com|iesdouyin\.com)/i.test(link);
        if (!link || !looksLikeVideo || link === lastClipboardLinkRef.current) return;
        lastClipboardLinkRef.current = link;
        Alert.alert('检测到视频链接', '已从手机剪贴板读取到一个视频链接，是否立即下载？', [
          { text: '取消', style: 'cancel' },
          { text: '确定下载', onPress: () => { setUrl(link); void downloadUnified(link); } },
        ]);
      }).catch(() => undefined);
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [tab, busy, appActive]);

  const addToKnowledge = async (row: DownloadRow) => {
    try {
      const result = await enrichWithAI(config, row);
      db.runSync('INSERT OR REPLACE INTO knowledge_items (download_id, title, summary, category, tags, created_at) VALUES (?, ?, ?, ?, ?, ?)', row.id, row.title, result?.summary || '', result?.category || '未分类', JSON.stringify(result?.tags || []), new Date().toISOString());
      db.runSync('UPDATE downloads SET in_knowledge = 1, category = ? WHERE id = ?', result?.category || '未分类', row.id);
      refresh();
    } catch (error) {
      Alert.alert('加入失败', error instanceof Error ? error.message : '无法加入知识库。');
    }
  };

  const openFile = async (row: DownloadRow) => {
    try {
      const localUri = normalizeLocalUri(row.local_uri);
      const info = await FileSystem.getInfoAsync(localUri);
      if (!info.exists) throw new Error('视频文件不存在，可能已被系统清理。');
      if (TermuxBridge && await TermuxBridge.openVideo(localUri)) return;
      Alert.alert('没有可用播放器', '手机上没有能直接打开这个视频的应用。你可以安装播放器后重试，或手动分享给其他应用。', [
        { text: '取消', style: 'cancel' },
        { text: '分享', onPress: async () => {
          try {
            if (await Sharing.isAvailableAsync()) await Sharing.shareAsync(localUri, { mimeType: 'video/mp4', dialogTitle: row.title });
            else await Share.share({ url: localUri, message: row.title });
          } catch (error) {
            Alert.alert('分享失败', error instanceof Error ? error.message : '无法分享这个视频。');
          }
        } },
      ]);
    } catch (error) {
      Alert.alert('打开失败', error instanceof Error ? error.message : '无法打开或分享这个视频。');
    }
  };

  const shareToWechat = async (row: DownloadRow) => {
    try {
      const localUri = normalizeLocalUri(row.local_uri);
      const info = await FileSystem.getInfoAsync(localUri);
      if (!info.exists) throw new Error('视频文件不存在，可能已被系统清理。');
      if (TermuxBridge?.shareVideoToWechat && await TermuxBridge.shareVideoToWechat(localUri)) return;
      if (await Sharing.isAvailableAsync()) await Sharing.shareAsync(localUri, { mimeType: 'video/mp4', dialogTitle: '发送到微信' });
      else Alert.alert('无法发送到微信', '手机上没有检测到微信或可用的分享组件。');
    } catch (error) {
      Alert.alert('发送失败', error instanceof Error ? error.message : '无法发送这个视频。');
    }
  };

  const deleteVideo = (row: DownloadRow) => {
    Alert.alert('删除视频？', `将删除“${row.title}”及其本地记录。此操作不可恢复。`, [
      { text: '取消', style: 'cancel' },
      {
        text: '删除',
        style: 'destructive',
        onPress: async () => {
          try {
            const localUri = normalizeLocalUri(row.local_uri);
            if (TermuxBridge && /^file:\/\/\/sdcard\//i.test(localUri)) await TermuxBridge.deleteFile(localUri);
            else await FileSystem.deleteAsync(localUri, { idempotent: true });
            db.runSync('DELETE FROM knowledge_items WHERE download_id = ?', row.id);
            db.runSync('DELETE FROM downloads WHERE id = ?', row.id);
            refresh();
          } catch (error) {
            Alert.alert('删除失败', error instanceof Error ? error.message : '无法删除这个视频。');
          }
        },
      },
    ]);
  };

  const ask = async () => {
    const q = question.trim();
    if (!q || asking) return;
    setAsking(true);
    setQuestion('');
    db.runSync('INSERT INTO assistant_messages (role, content, created_at) VALUES (?, ?, ?)', 'user', q, new Date().toISOString());
    const assistant = db.runSync('INSERT INTO assistant_messages (role, content, created_at) VALUES (?, ?, ?)', 'assistant', '正在检索本地知识库…', new Date().toISOString());
    const assistantId = Number(assistant.lastInsertRowId);
    setChatHistory(chatRows());
    try {
      const context = knowledgeContext(q).map((item) => `标题：${item.title}\n分类：${item.category}\n摘要：${item.summary || '暂无'}`).join('\n\n');
      const previous = chatRows().filter((item) => item.id !== assistantId).slice(-10).map((item) => ({ role: item.role, content: item.content }));
      const result = await askModel(config, [
        { role: 'system', content: '你是视频下载助手。问题和知识库相关时，优先依据提供的本地知识库回答；问题无关时直接回答，不要强行检索。知识库没有相关内容时明确说明，不要编造。' },
        ...previous,
        { role: 'user', content: `知识库内容：\n${context || '知识库为空'}\n\n问题：${q}` },
      ]);
      db.runSync('UPDATE assistant_messages SET content = ? WHERE id = ?', result || '没有得到有效回答。', assistantId);
      setChatHistory(chatRows());
    } catch (error) {
      db.runSync('UPDATE assistant_messages SET content = ? WHERE id = ?', error instanceof Error ? error.message : 'AI 请求失败。', assistantId);
      setChatHistory(chatRows());
    } finally {
      setAsking(false);
    }
  };

  const saveAI = async () => {
    setSavingConfig(true);
    try {
      const normalized = { ...config, baseUrl: normalizeBaseUrl(config.baseUrl) };
      await saveConfig(normalized);
      setConfig(normalized);
      Alert.alert('已保存', 'AI 配置只保存在这台手机的安全存储中。');
    } finally {
      setSavingConfig(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : 'height'} keyboardVerticalOffset={0}>
        {tab === 'home' && <HomeScreen url={url} setUrl={setUrl} busy={busy} download={downloadUnified} cancelDownload={cancelActiveDownload} downloadProgress={downloadProgress} downloadMode={downloadMode} completed={completed.length} categorized={categorized} rows={downloads} addToKnowledge={addToKnowledge} openFile={openFile} shareToWechat={shareToWechat} deleteVideo={deleteVideo} />}
        {tab === 'assistant' && <AssistantScreen question={question} setQuestion={setQuestion} messages={chatHistory} ask={ask} asking={asking} configured={Boolean(config.apiKey)} />}
        {tab === 'settings' && <SettingsScreen config={config} setConfig={setConfig} saveAI={saveAI} saving={savingConfig} authorizeWechat={authorizeWechat} yuanbaoAuthorized={yuanbaoAuthorized} />}
        <View style={styles.tabBar}>
          <TabButton icon="download-outline" label="下载" active={tab === 'home'} onPress={() => setTab('home')} />
          <TabButton icon="sparkles-outline" label="AI 助手" active={tab === 'assistant'} onPress={() => setTab('assistant')} />
          <TabButton icon="settings-outline" label="设置" active={tab === 'settings'} onPress={() => setTab('settings')} />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function HomeScreen({ url, setUrl, busy, download, cancelDownload, downloadProgress, downloadMode, completed, categorized, rows, addToKnowledge, openFile, shareToWechat, deleteVideo }: { url: string; setUrl: (value: string) => void; busy: boolean; download: () => void; cancelDownload: () => void; downloadProgress: number | null; downloadMode: 'yt-dlp' | 'wechat' | null; completed: number; categorized: number; rows: DownloadRow[]; addToKnowledge: (row: DownloadRow) => void; openFile: (row: DownloadRow) => void; shareToWechat: (row: DownloadRow) => void; deleteVideo: (row: DownloadRow) => void }) {
  return <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
    <View style={styles.card}><Text style={[styles.sectionTitle, styles.centerText]}>添加下载</Text><TextInput accessibilityLabel="视频链接" value={url} onChangeText={setUrl} placeholder="粘贴视频链接" placeholderTextColor="#9FB3C8" autoCapitalize="none" autoCorrect={false} style={styles.input} /><Pressable accessibilityRole="button" accessibilityLabel={busy ? '正在下载' : '下载视频'} onPress={() => download()} disabled={busy} style={({ pressed }) => [styles.primary, pressed && styles.pressed, busy && styles.disabled]}>{busy ? <ActivityIndicator color={COLORS.white} /> : <><Ionicons name="arrow-down-circle-outline" size={19} color={COLORS.white} /><Text style={styles.primaryText}>下载</Text></>}</Pressable>{busy ? <View style={styles.progressBox}><View style={styles.progressHeader}><Text style={styles.progressText}>{downloadMode === 'wechat' ? '正在解析视频号' : '正在解析并下载'}</Text><Text style={styles.progressPercent}>{downloadProgress === null ? '处理中' : `${Math.round(downloadProgress)}%`}</Text></View>{downloadProgress !== null ? <View style={styles.progressTrack}><View style={[styles.progressFill, { width: `${Math.max(2, Math.min(100, downloadProgress))}%` }]} /></View> : <ActivityIndicator size="small" color={COLORS.cyan} /> }<Pressable accessibilityRole="button" accessibilityLabel="取消下载" onPress={cancelDownload} style={({ pressed }) => [styles.cancelButton, pressed && styles.pressed]}><Text style={styles.cancelText}>取消下载</Text></Pressable></View> : null}</View>
    <View style={styles.stats}><Stat value={String(completed)} label="已下载" icon="checkmark-circle-outline" /><Stat value={String(categorized)} label="已入库" icon="library-outline" /><Stat value="手机" label="本地保存" icon="phone-portrait-outline" /></View>
    <RecentList rows={rows} addToKnowledge={addToKnowledge} openFile={openFile} shareToWechat={shareToWechat} deleteVideo={deleteVideo} />
  </ScrollView>;
}

function RecentList({ rows, addToKnowledge, openFile, shareToWechat, deleteVideo }: { rows: DownloadRow[]; addToKnowledge: (row: DownloadRow) => void; openFile: (row: DownloadRow) => void; shareToWechat: (row: DownloadRow) => void; deleteVideo: (row: DownloadRow) => void }) {
  return <View style={styles.recentBlock}><View style={styles.sectionHeader}><View><Text style={styles.pageTitle}>最近下载</Text><Text style={styles.helper}>视频文件和记录都保存在这台手机</Text></View><View style={styles.countPill}><Text style={styles.countText}>{rows.length}</Text></View></View>{rows.length === 0 ? <EmptyState icon="film-outline" title="还没有下载" text="回到下载页粘贴一个视频直链吧。" /> : rows.map((row) => <View style={styles.downloadRow} key={row.id}><View style={styles.videoIcon}><Ionicons name="play" size={16} color={COLORS.cyan} /></View><View style={styles.rowMain}><Text style={styles.rowTitle} numberOfLines={2}>{row.title}</Text><Text style={styles.rowMeta}>{new Date(row.created_at).toLocaleString()} · {row.category || '未分类'}</Text><View style={styles.rowActions}><Pressable accessibilityRole="button" accessibilityLabel={`打开视频：${row.title}`} onPress={() => openFile(row)} style={({ pressed }) => [styles.smallButton, pressed && styles.pressed]}><Ionicons name="play-outline" size={15} color={COLORS.cyan} /><Text style={styles.smallButtonText}>打开</Text></Pressable>{row.in_knowledge ? <View style={styles.inLibrary}><Ionicons name="checkmark" size={14} color={COLORS.success} /><Text style={styles.inLibraryText}>已入库</Text></View> : <Pressable accessibilityRole="button" accessibilityLabel={`加入知识库：${row.title}`} onPress={() => addToKnowledge(row)} style={({ pressed }) => [styles.smallButton, pressed && styles.pressed]}><Ionicons name="sparkles-outline" size={15} color={COLORS.cyan} /><Text style={styles.smallButtonText}>加入知识库</Text></Pressable>}<Pressable accessibilityRole="button" accessibilityLabel={`删除视频：${row.title}`} onPress={() => deleteVideo(row)} style={({ pressed }) => [styles.deleteButton, pressed && styles.pressed]}><Ionicons name="trash-outline" size={15} color={COLORS.danger} /><Text style={styles.deleteButtonText}>删除</Text></Pressable></View></View></View>)}</View>;
}

function AssistantScreen({ question, setQuestion, messages, ask, asking, configured }: { question: string; setQuestion: (value: string) => void; messages: ChatMessage[]; ask: () => void; asking: boolean; configured: boolean }) {
  return <View style={styles.flex}><ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled"><View style={styles.assistantHero}><View style={styles.assistantAvatar}><Ionicons name="sparkles" size={22} color={COLORS.white} /></View><View style={styles.flex}><Text style={styles.pageTitle}>AI 知识库助手</Text><Text style={styles.helper}>{configured ? '会先检索手机里的已入库内容' : '先去设置里连接一个 AI 模型'}</Text></View></View>{messages.length ? messages.map((message) => <View key={message.id} style={message.role === 'user' ? styles.questionBubble : styles.answerBubble}><Text style={message.role === 'user' ? styles.questionText : styles.answerText}>{message.content}</Text></View>) : <EmptyState icon="chatbubble-ellipses-outline" title="问问你的知识库" text="例如：我收藏了哪些室内设计视频？" />}</ScrollView><View style={styles.chatComposer}><TextInput accessibilityLabel="向视频库提问" editable={!asking} value={question} onChangeText={setQuestion} onSubmitEditing={ask} returnKeyType="send" blurOnSubmit={false} placeholder={asking ? '正在检索…' : '向视频库提问…'} placeholderTextColor="#9FB3C8" style={styles.chatInput} /><Pressable accessibilityRole="button" accessibilityLabel={asking ? '正在检索' : '发送问题'} disabled={asking} onPress={ask} style={({ pressed }) => [styles.sendButton, pressed && styles.pressed, asking && styles.disabled]}>{asking ? <ActivityIndicator color={COLORS.white} /> : <Ionicons name="arrow-up" size={18} color={COLORS.white} />}</Pressable></View></View>;
}

function SettingsScreen({ config, setConfig, saveAI, saving, authorizeWechat, yuanbaoAuthorized }: { config: AIConfig; setConfig: (value: AIConfig) => void; saveAI: () => void; saving: boolean; authorizeWechat: () => void; yuanbaoAuthorized: boolean }) {
  return <ScrollView contentContainerStyle={styles.content}><Text style={styles.pageTitle}>设置</Text><Text style={styles.helper}>授权信息只保存在手机安全存储中，不会上传给我。</Text><View style={styles.card}><Text style={styles.sectionTitle}>微信视频号</Text><Text style={styles.helper}>登录元宝后，应用会调用电脑版同样的解析流程。</Text><View style={styles.authStatus}><Ionicons name={yuanbaoAuthorized ? 'checkmark-circle-outline' : 'alert-circle-outline'} size={18} color={yuanbaoAuthorized ? COLORS.success : COLORS.danger} /><Text style={[styles.authStatusText, yuanbaoAuthorized && styles.authStatusOk]}>{yuanbaoAuthorized ? '已授权' : '未授权'}</Text></View><Pressable accessibilityRole="button" accessibilityLabel={yuanbaoAuthorized ? '重新进行元宝授权' : '元宝授权'} onPress={authorizeWechat} style={({ pressed }) => [styles.secondary, pressed && styles.pressed]}><Ionicons name="shield-checkmark-outline" size={18} color={COLORS.cyanDark} /><Text style={styles.secondaryText}>{yuanbaoAuthorized ? '重新授权' : '元宝授权'}</Text></Pressable></View><View style={styles.card}><Text style={styles.sectionTitle}>AI 配置</Text><Field label="API 地址" value={config.baseUrl} onChangeText={(value) => setConfig({ ...config, baseUrl: value })} placeholder="https://api.openai.com/v1" autoCapitalize="none" /><Field label="模型名称" value={config.model} onChangeText={(value) => setConfig({ ...config, model: value })} placeholder="gpt-4o-mini" autoCapitalize="none" /><Field label="API Key" value={config.apiKey} onChangeText={(value) => setConfig({ ...config, apiKey: value })} placeholder="sk-…" secureTextEntry autoCapitalize="none" /><Field label="温度" value={config.temperature} onChangeText={(value) => setConfig({ ...config, temperature: value })} placeholder="0.2" keyboardType="decimal-pad" /><Pressable accessibilityRole="button" accessibilityLabel="保存 AI 配置" onPress={saveAI} disabled={saving} style={({ pressed }) => [styles.primary, pressed && styles.pressed, saving && styles.disabled]}>{saving ? <ActivityIndicator color={COLORS.white} /> : <><Ionicons name="save-outline" size={18} color={COLORS.white} /><Text style={styles.primaryText}>保存 AI 配置</Text></>}</Pressable></View><View style={styles.tip}><Ionicons name="lock-closed-outline" size={18} color={COLORS.cyan} /><Text style={styles.tipText}>支持 OpenAI 兼容接口，也可填写 Agnes、DeepSeek、OpenRouter 或自建中转地址。地址可填带不带 /v1，应用会自动规范化。</Text></View></ScrollView>;
}

function Field({ label, value, onChangeText, placeholder, secureTextEntry, keyboardType, autoCapitalize }: { label: string; value: string; onChangeText: (value: string) => void; placeholder: string; secureTextEntry?: boolean; keyboardType?: 'decimal-pad'; autoCapitalize?: 'none' }) {
  return <View style={styles.field}><Text style={styles.fieldLabel}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={onChangeText} placeholder={placeholder} placeholderTextColor="#9FB3C8" secureTextEntry={secureTextEntry} keyboardType={keyboardType} autoCapitalize={autoCapitalize} autoCorrect={false} style={styles.input} /></View>;
}

function Stat({ value, label, icon }: { value: string; label: string; icon: keyof typeof Ionicons.glyphMap }) {
  return <View style={styles.stat}><Ionicons name={icon} size={19} color={COLORS.cyan} /><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></View>;
}

function TabButton({ icon, label, active, onPress }: { icon: keyof typeof Ionicons.glyphMap; label: string; active: boolean; onPress: () => void }) {
  return <Pressable accessibilityRole="tab" accessibilityState={{ selected: active }} accessibilityLabel={label} onPress={onPress} style={({ pressed }) => [styles.tabButton, pressed && styles.pressed]}><Ionicons name={icon} size={22} color={active ? COLORS.cyan : COLORS.muted} /><Text style={[styles.tabLabel, active && styles.tabLabelActive]}>{label}</Text></Pressable>;
}

function EmptyState({ icon, title, text }: { icon: keyof typeof Ionicons.glyphMap; title: string; text: string }) {
  return <View style={styles.empty}><Ionicons name={icon} size={30} color="#9FB3C8" /><Text style={styles.emptyTitle}>{title}</Text><Text style={styles.emptyText}>{text}</Text></View>;
}

const makeStyles = (colors: typeof COLORS) => StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.faint },
  flex: { flex: 1 },
  title: { marginTop: 2, fontSize: 21, fontWeight: '800', color: colors.ink },
  content: { padding: 20, paddingBottom: 32, gap: 16 },
  card: { backgroundColor: colors.white, borderRadius: 20, borderWidth: 1, borderColor: colors.line, padding: 18, gap: 10 },
  sectionTitle: { fontSize: 18, fontWeight: '800', color: colors.ink },
  centerText: { textAlign: 'center' },
  pageTitle: { fontSize: 22, fontWeight: '800', color: colors.ink },
  helper: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  input: { minHeight: 48, borderRadius: 13, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.white, color: colors.ink, paddingHorizontal: 14, fontSize: 15 },
  primary: { minHeight: 49, borderRadius: 14, backgroundColor: colors.cyan, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 8, paddingHorizontal: 18 },
  primaryText: { color: colors.white, fontSize: 15, fontWeight: '800' },
  progressBox: { marginTop: 2, gap: 8, alignItems: 'stretch' },
  progressHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  progressText: { color: colors.muted, fontSize: 12, fontWeight: '700' },
  progressPercent: { color: colors.cyanDark, fontSize: 12, fontWeight: '800' },
  progressTrack: { height: 7, borderRadius: 4, overflow: 'hidden', backgroundColor: colors.cyanTint },
  progressFill: { height: '100%', borderRadius: 4, backgroundColor: colors.cyan },
  cancelButton: { minHeight: 44, borderRadius: 12, borderWidth: 1, borderColor: colors.line, justifyContent: 'center', alignItems: 'center' },
  cancelText: { color: colors.cyanDark, fontSize: 13, fontWeight: '700' },
  secondary: { minHeight: 46, borderRadius: 14, backgroundColor: colors.cyanTint, borderWidth: 1, borderColor: colors.line, flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 8, paddingHorizontal: 18 },
  secondaryText: { color: colors.cyanDark, fontSize: 14, fontWeight: '800' },
  authStatus: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  authStatusText: { color: colors.danger, fontSize: 13, fontWeight: '700' },
  authStatusOk: { color: colors.success },
  pressed: { opacity: 0.82 },
  disabled: { opacity: 0.55 },
  stats: { flexDirection: 'row', gap: 10 },
  stat: { flex: 1, backgroundColor: colors.white, borderRadius: 16, borderWidth: 1, borderColor: colors.line, padding: 13, minHeight: 94 },
  statValue: { color: colors.ink, fontSize: 21, fontWeight: '800', marginTop: 8 },
  statLabel: { color: colors.muted, fontSize: 12, marginTop: 2 },
  tip: { flexDirection: 'row', gap: 8, backgroundColor: colors.cyanTint, borderRadius: 14, padding: 13, alignItems: 'flex-start' },
  tipText: { flex: 1, color: colors.cyanDark, fontSize: 13, lineHeight: 19 },
  tabBar: { flexDirection: 'row', backgroundColor: colors.white, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 7, paddingBottom: Platform.OS === 'ios' ? 8 : 5 },
  tabButton: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 3, paddingVertical: 5, minHeight: 48 },
  tabLabel: { color: colors.muted, fontSize: 11, fontWeight: '600' },
  tabLabelActive: { color: colors.cyan, fontWeight: '800' },
  recentBlock: { gap: 12 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  countPill: { backgroundColor: colors.cyanTint, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 20 },
  countText: { color: colors.cyanDark, fontWeight: '800' },
  downloadRow: { backgroundColor: colors.white, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14, flexDirection: 'row', gap: 12 },
  videoIcon: { width: 38, height: 38, borderRadius: 12, backgroundColor: colors.cyanTint, justifyContent: 'center', alignItems: 'center' },
  rowMain: { flex: 1, gap: 4 },
  rowTitle: { color: colors.ink, fontSize: 15, lineHeight: 21, fontWeight: '700' },
  rowMeta: { color: colors.muted, fontSize: 11 },
  rowActions: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginTop: 6 },
  smallButton: { borderWidth: 1, borderColor: colors.line, borderRadius: 9, minHeight: 44, paddingHorizontal: 11, paddingVertical: 8, flexDirection: 'row', gap: 4, alignItems: 'center' },
  smallButtonText: { color: colors.cyanDark, fontSize: 11, fontWeight: '700' },
  deleteButton: { borderWidth: 1, borderColor: colors.danger, borderRadius: 9, minHeight: 44, paddingHorizontal: 11, paddingVertical: 8, flexDirection: 'row', gap: 4, alignItems: 'center' },
  deleteButtonText: { color: colors.danger, fontSize: 11, fontWeight: '700' },
  inLibrary: { flexDirection: 'row', alignItems: 'center', gap: 3, paddingHorizontal: 8 },
  inLibraryText: { color: colors.success, fontSize: 11, fontWeight: '700' },
  empty: { backgroundColor: colors.white, borderRadius: 18, borderWidth: 1, borderColor: colors.line, borderStyle: 'dashed', alignItems: 'center', padding: 30, gap: 7 },
  emptyTitle: { color: colors.ink, fontSize: 16, fontWeight: '800' },
  emptyText: { color: colors.muted, fontSize: 13, textAlign: 'center' },
  assistantHero: { backgroundColor: colors.white, borderRadius: 20, borderWidth: 1, borderColor: colors.line, padding: 16, flexDirection: 'row', alignItems: 'center', gap: 12 },
  assistantAvatar: { width: 44, height: 44, borderRadius: 15, backgroundColor: colors.cyan, justifyContent: 'center', alignItems: 'center' },
  answerBubble: { backgroundColor: colors.white, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 16 },
  answerText: { color: colors.ink, fontSize: 15, lineHeight: 23 },
  questionBubble: { alignSelf: 'flex-end', maxWidth: '88%', backgroundColor: colors.cyan, borderRadius: 18, paddingHorizontal: 16, paddingVertical: 12 },
  questionText: { color: colors.white, fontSize: 15, lineHeight: 22 },
  chatComposer: { backgroundColor: colors.white, borderTopWidth: 1, borderTopColor: colors.line, padding: 12, flexDirection: 'row', gap: 8 },
  chatInput: { flex: 1, minHeight: 46, borderRadius: 14, borderWidth: 1, borderColor: colors.line, paddingHorizontal: 14, color: colors.ink },
  sendButton: { width: 46, height: 46, borderRadius: 14, backgroundColor: colors.cyan, justifyContent: 'center', alignItems: 'center' },
  field: { gap: 6 },
  fieldLabel: { color: colors.ink, fontSize: 13, fontWeight: '700' },
});
const styles = makeStyles(COLORS);
