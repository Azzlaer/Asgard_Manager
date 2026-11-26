using System;
using BepInEx;
using BepInEx.Configuration;
using UnityEngine;
using Asgard.Core;

namespace Asgard.MasterUI
{
    [BepInPlugin(Guid, Name, Version)]
    [BepInProcess("valheim.exe")]
    [BepInDependency(AsgardCorePlugin.Guid)]
    public sealed class AsgardMasterUIPlugin : BaseUnityPlugin
    {
        public const string Guid = "com.asgard.client.masterui";
        public const string Name = "ASGARD Master Panel";
        public const string Version = "7.0.6";

        private static readonly Color VoidBlack = new Color(0.012f, 0.008f, 0.012f, 0.98f);
        private static readonly Color PanelBlack = new Color(0.035f, 0.018f, 0.022f, 0.98f);
        private static readonly Color PanelRaised = new Color(0.075f, 0.025f, 0.032f, 0.98f);
        private static readonly Color Crimson = new Color(0.92f, 0.025f, 0.055f, 1f);
        private static readonly Color CrimsonSoft = new Color(1f, 0.18f, 0.22f, 1f);
        private static readonly Color BloodDark = new Color(0.24f, 0.005f, 0.02f, 1f);
        private static readonly Color TextMain = new Color(0.97f, 0.91f, 0.92f, 1f);
        private static readonly Color TextMuted = new Color(0.62f, 0.48f, 0.51f, 1f);
        private static readonly Color Success = new Color(0.30f, 0.95f, 0.55f, 1f);
        private static readonly Color Warning = new Color(1f, 0.62f, 0.12f, 1f);

        private ConfigEntry<KeyCode> _key;
        private bool _open;
        private bool _firstOpen = true;
        private Rect _window = new Rect(80, 55, 1080, 700);
        private int _tab;
        private Vector2 _scroll;
        private bool _previousCursorVisible;
        private CursorLockMode _previousCursorLock;
        private float _lastGuiErrorTime = -100f;
        private string _lastGuiError = "";

        private Texture2D _voidTexture;
        private Texture2D _panelTexture;
        private Texture2D _raisedTexture;
        private Texture2D _crimsonTexture;
        private Texture2D _bloodTexture;
        private Texture2D _softTexture;
        private Texture2D _successTexture;
        private Texture2D _warningTexture;

        private GUIStyle _windowStyle;
        private GUIStyle _brandStyle;
        private GUIStyle _subtitleStyle;
        private GUIStyle _sectionStyle;
        private GUIStyle _bodyStyle;
        private GUIStyle _mutedStyle;
        private GUIStyle _metricStyle;
        private GUIStyle _metricValueStyle;
        private GUIStyle _navStyle;
        private GUIStyle _navActiveStyle;
        private GUIStyle _buttonStyle;
        private GUIStyle _dangerButtonStyle;
        private GUIStyle _smallButtonStyle;
        private GUIStyle _pillStyle;
        private GUIStyle _footerStyle;

        private readonly string[] _tabs =
        {
            "NEXUS",
            "JUGADORES",
            "ASGARD AUDIT",
            "SENTENCIAS",
            "SERVIDOR",
            "RECURSOS"
        };

        private readonly string[] _tabGlyphs = { "◈", "◆", "⌁", "✦", "⬢", "▰" };

        private void Awake()
        {
            _key = Config.Bind("UI", "ToggleKey", KeyCode.F8, "Abre el panel maestro.");
            Logger.LogInfo("ASGARD Master Panel 7.0.6 Crimson Void preparado. Tecla=" + _key.Value);
        }

        private void Update()
        {
            if (Input.GetKeyDown(_key.Value)) SetOpen(!_open);
            if (_open && Input.GetKeyDown(KeyCode.Escape)) SetOpen(false);
        }

        private void SetOpen(bool value)
        {
            if (_open == value) return;
            _open = value;
            if (_open)
            {
                _previousCursorVisible = Cursor.visible;
                _previousCursorLock = Cursor.lockState;
                Cursor.visible = true;
                Cursor.lockState = CursorLockMode.None;
                if (_firstOpen)
                {
                    _window.x = Mathf.Max(12f, (Screen.width - _window.width) * 0.5f);
                    _window.y = Mathf.Max(12f, (Screen.height - _window.height) * 0.5f);
                    _firstOpen = false;
                }
            }
            else
            {
                Cursor.visible = _previousCursorVisible;
                Cursor.lockState = _previousCursorLock;
            }
        }

        private void OnDestroy()
        {
            if (_open) SetOpen(false);
            DestroyTexture(_voidTexture);
            DestroyTexture(_panelTexture);
            DestroyTexture(_raisedTexture);
            DestroyTexture(_crimsonTexture);
            DestroyTexture(_bloodTexture);
            DestroyTexture(_softTexture);
            DestroyTexture(_successTexture);
            DestroyTexture(_warningTexture);
        }

        private static void DestroyTexture(Texture2D texture)
        {
            if (texture != null) UnityEngine.Object.Destroy(texture);
        }

        private void OnGUI()
        {
            if (!_open) return;
            try
            {
                EnsureTheme();
                _window.width = Mathf.Min(1080f, Mathf.Max(860f, Screen.width - 30f));
                _window.height = Mathf.Min(700f, Mathf.Max(600f, Screen.height - 30f));
                _window.x = Mathf.Clamp(_window.x, 0f, Mathf.Max(0f, Screen.width - _window.width));
                _window.y = Mathf.Clamp(_window.y, 0f, Mathf.Max(0f, Screen.height - _window.height));
                GUI.color = Color.white;
                _window = GUI.Window(77001, _window, DrawWindow, GUIContent.none, _windowStyle);
            }
            catch (Exception ex)
            {
                _lastGuiError = ex.GetType().Name + ": " + ex.Message;
                if (Time.realtimeSinceStartup - _lastGuiErrorTime > 5f)
                {
                    _lastGuiErrorTime = Time.realtimeSinceStartup;
                    Logger.LogError("ASGARD UI protegida: " + ex);
                }
                DrawEmergencyPanel();
            }
        }

        private void EnsureTheme()
        {
            if (_voidTexture != null) return;
            _voidTexture = Solid(VoidBlack);
            _panelTexture = Solid(PanelBlack);
            _raisedTexture = Solid(PanelRaised);
            _crimsonTexture = Solid(Crimson);
            _bloodTexture = Solid(BloodDark);
            _softTexture = Solid(new Color(0.40f, 0.03f, 0.055f, 1f));
            _successTexture = Solid(new Color(0.08f, 0.30f, 0.18f, 1f));
            _warningTexture = Solid(new Color(0.35f, 0.18f, 0.02f, 1f));

            _windowStyle = new GUIStyle(GUI.skin.window)
            {
                normal = { background = _voidTexture },
                border = new RectOffset(0, 0, 0, 0),
                padding = new RectOffset(0, 0, 0, 0)
            };
            _brandStyle = Label(30, FontStyle.Bold, TextMain);
            _subtitleStyle = Label(12, FontStyle.Bold, CrimsonSoft);
            _sectionStyle = Label(18, FontStyle.Bold, TextMain);
            _bodyStyle = Label(13, FontStyle.Normal, TextMain);
            _bodyStyle.wordWrap = true;
            _mutedStyle = Label(12, FontStyle.Normal, TextMuted);
            _mutedStyle.wordWrap = true;
            _metricStyle = Label(10, FontStyle.Bold, TextMuted);
            _metricValueStyle = Label(20, FontStyle.Bold, TextMain);
            _footerStyle = Label(11, FontStyle.Normal, TextMuted);
            _footerStyle.alignment = TextAnchor.MiddleRight;

            _navStyle = new GUIStyle(GUI.skin.button)
            {
                fontSize = 12,
                fontStyle = FontStyle.Bold,
                alignment = TextAnchor.MiddleLeft,
                padding = new RectOffset(20, 8, 0, 0),
                normal = { background = _panelTexture, textColor = TextMuted },
                hover = { background = _raisedTexture, textColor = TextMain },
                active = { background = _bloodTexture, textColor = Color.white },
                fixedHeight = 46f
            };
            _navActiveStyle = new GUIStyle(_navStyle)
            {
                normal = { background = _bloodTexture, textColor = Color.white },
                hover = { background = _softTexture, textColor = Color.white }
            };
            _buttonStyle = Button(_raisedTexture, _softTexture, TextMain, 13, 38f);
            _dangerButtonStyle = Button(_bloodTexture, _crimsonTexture, Color.white, 13, 40f);
            _smallButtonStyle = Button(_panelTexture, _raisedTexture, TextMain, 11, 28f);
            _pillStyle = new GUIStyle(_bodyStyle)
            {
                alignment = TextAnchor.MiddleCenter,
                fontSize = 10,
                fontStyle = FontStyle.Bold
            };
        }

        private static GUIStyle Label(int size, FontStyle fontStyle, Color color)
        {
            return new GUIStyle(GUI.skin.label)
            {
                fontSize = size,
                fontStyle = fontStyle,
                normal = { textColor = color }
            };
        }

        private static GUIStyle Button(Texture2D normal, Texture2D hover, Color text, int fontSize, float height)
        {
            return new GUIStyle(GUI.skin.button)
            {
                fontSize = fontSize,
                fontStyle = FontStyle.Bold,
                alignment = TextAnchor.MiddleCenter,
                fixedHeight = height,
                normal = { background = normal, textColor = text },
                hover = { background = hover, textColor = Color.white },
                active = { background = hover, textColor = Color.white },
                padding = new RectOffset(12, 12, 0, 0)
            };
        }

        private static Texture2D Solid(Color color)
        {
            var texture = new Texture2D(1, 1, TextureFormat.RGBA32, false);
            texture.name = "ASGARD_UI_" + color.ToString();
            texture.SetPixel(0, 0, color);
            texture.Apply(false, true);
            return texture;
        }

        private void DrawWindow(int id)
        {
            DrawBackdrop();
            DrawHeader();
            DrawSidebar();
            DrawContent();
            DrawFooter();
            GUI.DragWindow(new Rect(0, 0, _window.width, 88));
        }

        private void DrawBackdrop()
        {
            GUI.DrawTexture(new Rect(0, 0, _window.width, _window.height), _voidTexture);
            float pulse = 0.45f + 0.35f * Mathf.Sin(Time.realtimeSinceStartup * 1.8f);
            DrawRect(new Rect(0, 0, _window.width, 3), new Color(1f, 0.02f, 0.04f, 0.65f + pulse * 0.25f));
            DrawRect(new Rect(0, 3, _window.width, 9), new Color(0.6f, 0f, 0.02f, 0.08f + pulse * 0.08f));
            DrawRect(new Rect(0, 88, _window.width, 1), new Color(0.75f, 0.02f, 0.05f, 0.50f));
            DrawRect(new Rect(212, 88, 1, _window.height - 88), new Color(0.65f, 0.02f, 0.04f, 0.35f));
            DrawVoidNoise();
        }

        private void DrawVoidNoise()
        {
            float width = _window.width;
            float height = _window.height;
            for (int i = 0; i < 18; i++)
            {
                float x = Mathf.Repeat(i * 137.3f + Time.realtimeSinceStartup * (2f + i * 0.08f), width);
                float y = 92f + Mathf.Repeat(i * 83.7f, Mathf.Max(1f, height - 110f));
                float alpha = 0.025f + (i % 3) * 0.012f;
                DrawRect(new Rect(x, y, 1f + i % 2, 1f + i % 2), new Color(1f, 0.05f, 0.08f, alpha));
            }
        }

        private void DrawHeader()
        {
            DrawVoidSigil(new Vector2(44, 44), 25f);
            GUI.Label(new Rect(82, 17, 630, 40), "ASGARD // CRIMSON VOID", _brandStyle);
            GUI.Label(new Rect(84, 56, 650, 20), "MASTER COMMAND INTERFACE  •  AUDIT  •  SENTENCE ENGINE", _subtitleStyle);

            string coreState = AsgardCorePlugin.IsReady ? "CORE ONLINE" : "CORE DEGRADED";
            Color coreColor = AsgardCorePlugin.IsReady ? Success : Warning;
            DrawPill(new Rect(_window.width - 310, 26, 132, 28), coreState, coreColor);
            if (GUI.Button(new Rect(_window.width - 157, 25, 104, 30), "CERRAR", _smallButtonStyle)) SetOpen(false);
            GUI.Label(new Rect(_window.width - 350, 58, 296, 18), "F8 abre/cierra  •  ESC cierra", _footerStyle);
        }

        private void DrawVoidSigil(Vector2 center, float radius)
        {
            float pulse = 0.75f + 0.25f * Mathf.Sin(Time.realtimeSinceStartup * 2.4f);
            for (int ring = 0; ring < 3; ring++)
            {
                float r = radius - ring * 6f;
                Color color = new Color(1f, 0.02f, 0.05f, (0.25f + ring * 0.15f) * pulse);
                DrawCircle(center, r, color, 2f, 28);
            }
            DrawLine(center + new Vector2(-16, 16), center + new Vector2(16, -16), CrimsonSoft, 3f);
            DrawLine(center + new Vector2(-12, -17), center + new Vector2(12, 17), new Color(0.45f, 0.01f, 0.03f, 1f), 2f);
            DrawRect(new Rect(center.x - 3, center.y - 3, 6, 6), Crimson);
        }

        private void DrawSidebar()
        {
            GUI.DrawTexture(new Rect(0, 89, 212, _window.height - 89), _panelTexture);
            GUI.Label(new Rect(20, 108, 180, 20), "COMANDO", _subtitleStyle);
            float y = 142f;
            for (int i = 0; i < _tabs.Length; i++)
            {
                Rect buttonRect = new Rect(12, y, 188, 46);
                if (_tab == i) DrawRect(new Rect(12, y, 3, 46), Crimson);
                string label = _tabGlyphs[i] + "   " + _tabs[i];
                if (GUI.Button(buttonRect, label, _tab == i ? _navActiveStyle : _navStyle))
                {
                    _tab = i;
                    _scroll = Vector2.zero;
                }
                y += 52f;
            }

            Rect statusBox = new Rect(14, _window.height - 150, 184, 118);
            DrawPanel(statusBox, true);
            GUI.Label(new Rect(statusBox.x + 14, statusBox.y + 12, 158, 18), "NEXUS STATUS", _metricStyle);
            GUI.Label(new Rect(statusBox.x + 14, statusBox.y + 35, 158, 24), AsgardCorePlugin.CurrentBridgeState, _bodyStyle);
            GUI.Label(new Rect(statusBox.x + 14, statusBox.y + 61, 158, 44), Trim(AsgardCorePlugin.CurrentBridgeDetail, 70), _mutedStyle);
        }

        private void DrawContent()
        {
            Rect viewport = new Rect(232, 105, _window.width - 252, _window.height - 142);
            Rect content = new Rect(0, 0, viewport.width - 20, Mathf.Max(viewport.height, GetContentHeight()));
            _scroll = GUI.BeginScrollView(viewport, _scroll, content, false, true);
            try
            {
                switch (_tab)
                {
                    case 0: DrawDashboard(content.width); break;
                    case 1: DrawPlayers(content.width); break;
                    case 2: DrawAudit(content.width); break;
                    case 3: DrawSentences(content.width); break;
                    case 4: DrawServer(content.width); break;
                    case 5: DrawResources(content.width); break;
                }
            }
            finally
            {
                GUI.EndScrollView();
            }
        }

        private float GetContentHeight()
        {
            return _tab == 0 ? 760f : 650f;
        }

        private void DrawDashboard(float width)
        {
            GUI.Label(new Rect(8, 0, width - 16, 30), "NEXUS DE CONTROL", _sectionStyle);
            GUI.Label(new Rect(8, 32, width - 16, 38), "Supervisión del servidor, integridad del puente y estado de la sentencia encarnada.", _mutedStyle);

            float gap = 12f;
            float cardWidth = (width - 16f - gap * 3f) / 4f;
            DrawMetricCard(new Rect(8, 84, cardWidth, 104), "ASGARD CORE", AsgardCorePlugin.IsReady ? "ONLINE" : "DEGRADED", AsgardCorePlugin.IsReady ? Success : Warning, "v" + AsgardCorePlugin.Version);
            DrawMetricCard(new Rect(8 + (cardWidth + gap), 84, cardWidth, 104), "HOST BRIDGE", AsgardCorePlugin.CurrentBridgeState, BridgeColor(), "ID " + AsgardCorePlugin.CurrentServerId);
            DrawMetricCard(new Rect(8 + (cardWidth + gap) * 2, 84, cardWidth, 104), "ENFORCEMENT", AsgardCorePlugin.CurrentMode.ToUpperInvariant(), ModeColor(), "Threshold protegido");
            DrawMetricCard(new Rect(8 + (cardWidth + gap) * 3, 84, cardWidth, 104), "JUGADORES", GetPlayerCount(), CrimsonSoft, GetConnectionLabel());

            Rect sentence = new Rect(8, 206, width - 16, 238);
            DrawPanel(sentence, true);
            GUI.Label(new Rect(sentence.x + 22, sentence.y + 18, 520, 28), "PROTOCOLO: ANTICHEAT ENCARNADO", _sectionStyle);
            GUI.Label(new Rect(sentence.x + 22, sentence.y + 52, sentence.width - 44, 40), "La cadena de evidencia permanece aislada del efecto visual. Ninguna sentencia automática se ejecuta sin identidad y severidad válidas.", _mutedStyle);
            DrawProtocolStep(new Rect(sentence.x + 22, sentence.y + 104, 142, 78), "01", "DETECCIÓN", "Audit captura evidencia");
            DrawProtocolConnector(sentence.x + 166, sentence.y + 142, 30);
            DrawProtocolStep(new Rect(sentence.x + 198, sentence.y + 104, 142, 78), "02", "VEREDICTO", "Core valida reglas");
            DrawProtocolConnector(sentence.x + 342, sentence.y + 142, 30);
            DrawProtocolStep(new Rect(sentence.x + 374, sentence.y + 104, 142, 78), "03", "MANIFESTACIÓN", "Avatar entra al mundo");
            DrawProtocolConnector(sentence.x + 518, sentence.y + 142, 30);
            DrawProtocolStep(new Rect(sentence.x + 550, sentence.y + 104, 142, 78), "04", "SENTENCIA", "Muerte + baneo");

            Rect action = new Rect(8, 462, width - 16, 158);
            DrawPanel(action, false);
            GUI.Label(new Rect(action.x + 22, action.y + 18, 460, 26), "DIAGNÓSTICO DEL NEXUS", _sectionStyle);
            GUI.Label(new Rect(action.x + 22, action.y + 51, action.width - 300, 54), GetDiagnosticText(), _bodyStyle);
            if (GUI.Button(new Rect(action.x + action.width - 250, action.y + 48, 208, 42), "ENVIAR PULSO DE PRUEBA", _buttonStyle)) SendAuditPulse();
            GUI.Label(new Rect(action.x + 22, action.y + 115, action.width - 44, 22), "Este botón solo registra una auditoría de diagnóstico. No castiga ni modifica el mundo.", _mutedStyle);

            if (!string.IsNullOrEmpty(_lastGuiError))
            {
                Rect error = new Rect(8, 638, width - 16, 90);
                DrawPanel(error, true);
                GUI.Label(new Rect(error.x + 18, error.y + 15, error.width - 36, 22), "PROTECCIÓN DE INTERFAZ ACTIVADA", _subtitleStyle);
                GUI.Label(new Rect(error.x + 18, error.y + 42, error.width - 36, 35), _lastGuiError, _mutedStyle);
            }
        }

        private void DrawPlayers(float width)
        {
            DrawModuleHeader(width, "JUGADORES", "Identidad, conexión, historial y acciones moderadas por permisos del servidor.");
            DrawTableShell(new Rect(8, 80, width - 16, 390), new[] { "JUGADOR", "PLATAFORMA", "ESTADO", "SESIÓN" });
            string playerName = Player.m_localPlayer != null ? Player.m_localPlayer.GetPlayerName() : "Esperando personaje";
            DrawTableRow(new Rect(24, 146, width - 48, 44), new[] { playerName, "LOCAL", Player.m_localPlayer != null ? "EN LÍNEA" : "NO DISPONIBLE", "ADMIN" });
            DrawComingSoon(new Rect(8, 492, width - 16, 118), "RPC AUTENTICADO", "La lista remota y las acciones Kick/Ban se habilitarán únicamente cuando el servidor confirme el rol administrativo.");
        }

        private void DrawAudit(float width)
        {
            DrawModuleHeader(width, "ASGARD AUDIT", "Trazabilidad de construcción, daño, destrucción, terreno y administración.");
            DrawFilterStrip(new Rect(8, 80, width - 16, 72), new[] { "Jugador", "Acción", "Prefab", "Severidad" });
            DrawComingSoon(new Rect(8, 172, width - 16, 320), "STREAM DE EVIDENCIA", "El módulo mostrará eventos firmados por el servidor. La Foundation R6 prioriza estabilidad del Core y la nueva interfaz Crimson Void.");
        }

        private void DrawSentences(float width)
        {
            DrawModuleHeader(width, "SENTENCIAS", "Cola de infracciones críticas y manifestaciones del Anticheat Encarnado.");
            DrawMetricCard(new Rect(8, 82, (width - 28) / 2, 112), "MODO ACTUAL", AsgardCorePlugin.CurrentMode.ToUpperInvariant(), ModeColor(), "observe recomendado para calibración");
            DrawMetricCard(new Rect(20 + (width - 28) / 2, 82, (width - 28) / 2, 112), "AVATAR", "ARMADO", Crimson, "Vanilla / Enhanced");
            DrawComingSoon(new Rect(8, 216, width - 16, 292), "COLA DE VEREDICTOS", "Aquí aparecerán identidad, evidencia, severidad, modo del Avatar y estado del baneo. Las acciones extremas exigirán confirmación o modo automático explícito.");
        }

        private void DrawServer(float width)
        {
            DrawModuleHeader(width, "SERVIDOR", "Guardado, backups, reinicios, anuncios y modificadores del mundo.");
            DrawActionGrid(width, new[] { "GUARDAR MUNDO", "BACKUP INMEDIATO", "ANUNCIAR REINICIO", "CANCELAR REINICIO", "ESTADO PLAYFAB", "JOIN CODE" });
            DrawComingSoon(new Rect(8, 330, width - 16, 174), "PUENTE ADMINISTRATIVO", "Las órdenes saldrán del cliente, serán verificadas en el servidor y finalmente ejecutadas por ASGARD Host Manager. El cliente nunca obtendrá acceso arbitrario a Windows.");
        }

        private void DrawResources(float width)
        {
            DrawModuleHeader(width, "RECURSOS", "CPU, memoria, afinidad física y perfiles del host desde el juego.");
            DrawMetricCard(new Rect(8, 82, (width - 40) / 3, 108), "PERFIL", "EQUILIBRADO", CrimsonSoft, "Gestionado por Host Manager");
            DrawMetricCard(new Rect(20 + (width - 40) / 3, 82, (width - 40) / 3, 108), "CPU", "-- %", Warning, "Esperando telemetría");
            DrawMetricCard(new Rect(32 + ((width - 40) / 3) * 2, 82, (width - 40) / 3, 108), "RAM", "-- GB", Warning, "Esperando telemetría");
            DrawComingSoon(new Rect(8, 214, width - 16, 290), "CONTROL DE NÚCLEOS", "La vista mostrará núcleos físicos disponibles y permitidos. Los cambios se enviarán al agente del host; el mod nunca manipulará procesos de Windows directamente.");
        }

        private void DrawModuleHeader(float width, string title, string subtitle)
        {
            GUI.Label(new Rect(8, 0, width - 16, 30), title, _sectionStyle);
            GUI.Label(new Rect(8, 34, width - 16, 34), subtitle, _mutedStyle);
        }

        private void DrawMetricCard(Rect rect, string label, string value, Color accent, string detail)
        {
            DrawPanel(rect, false);
            DrawRect(new Rect(rect.x, rect.y, 3, rect.height), accent);
            GUI.Label(new Rect(rect.x + 16, rect.y + 13, rect.width - 28, 16), label, _metricStyle);
            GUI.Label(new Rect(rect.x + 16, rect.y + 36, rect.width - 28, 28), Trim(value, 22), _metricValueStyle);
            GUI.Label(new Rect(rect.x + 16, rect.y + 75, rect.width - 28, 18), Trim(detail, 34), _mutedStyle);
        }

        private void DrawPanel(Rect rect, bool crimsonEdge)
        {
            GUI.DrawTexture(rect, _panelTexture);
            DrawOutline(rect, crimsonEdge ? new Color(0.72f, 0.015f, 0.04f, 0.72f) : new Color(0.35f, 0.04f, 0.06f, 0.58f), 1f);
            DrawRect(new Rect(rect.x + 1, rect.y + 1, rect.width - 2, 1), new Color(1f, 0.08f, 0.10f, crimsonEdge ? 0.22f : 0.10f));
        }

        private void DrawPill(Rect rect, string text, Color accent)
        {
            GUI.DrawTexture(rect, _panelTexture);
            DrawOutline(rect, new Color(accent.r, accent.g, accent.b, 0.75f), 1f);
            Color old = _pillStyle.normal.textColor;
            _pillStyle.normal.textColor = accent;
            GUI.Label(rect, text, _pillStyle);
            _pillStyle.normal.textColor = old;
        }

        private void DrawProtocolStep(Rect rect, string number, string title, string detail)
        {
            DrawPanel(rect, false);
            GUI.Label(new Rect(rect.x + 12, rect.y + 8, 34, 24), number, _subtitleStyle);
            GUI.Label(new Rect(rect.x + 12, rect.y + 32, rect.width - 24, 20), title, _bodyStyle);
            GUI.Label(new Rect(rect.x + 12, rect.y + 54, rect.width - 24, 18), detail, _mutedStyle);
        }

        private void DrawProtocolConnector(float x, float y, float width)
        {
            DrawLine(new Vector2(x, y), new Vector2(x + width, y), new Color(0.9f, 0.02f, 0.05f, 0.65f), 2f);
            DrawLine(new Vector2(x + width - 6, y - 4), new Vector2(x + width, y), Crimson, 2f);
            DrawLine(new Vector2(x + width - 6, y + 4), new Vector2(x + width, y), Crimson, 2f);
        }

        private void DrawTableShell(Rect rect, string[] headers)
        {
            DrawPanel(rect, false);
            DrawRect(new Rect(rect.x, rect.y, rect.width, 48), BloodDark);
            float column = rect.width / headers.Length;
            for (int i = 0; i < headers.Length; i++)
                GUI.Label(new Rect(rect.x + i * column + 14, rect.y + 15, column - 20, 20), headers[i], _metricStyle);
        }

        private void DrawTableRow(Rect rect, string[] cells)
        {
            DrawRect(rect, new Color(0.09f, 0.025f, 0.032f, 0.72f));
            float column = rect.width / cells.Length;
            for (int i = 0; i < cells.Length; i++)
                GUI.Label(new Rect(rect.x + i * column + 12, rect.y + 12, column - 18, 22), cells[i], _bodyStyle);
        }

        private void DrawFilterStrip(Rect rect, string[] labels)
        {
            DrawPanel(rect, false);
            float w = (rect.width - 30) / labels.Length;
            for (int i = 0; i < labels.Length; i++)
            {
                Rect field = new Rect(rect.x + 12 + i * w, rect.y + 17, w - 10, 38);
                GUI.Button(field, labels[i] + "  ▾", _smallButtonStyle);
            }
        }

        private void DrawComingSoon(Rect rect, string title, string text)
        {
            DrawPanel(rect, true);
            DrawVoidSigil(new Vector2(rect.x + 55, rect.y + rect.height * 0.5f), 24f);
            GUI.Label(new Rect(rect.x + 100, rect.y + 28, rect.width - 130, 28), title, _sectionStyle);
            GUI.Label(new Rect(rect.x + 100, rect.y + 67, rect.width - 130, rect.height - 80), text, _bodyStyle);
        }

        private void DrawActionGrid(float width, string[] actions)
        {
            float gap = 12f;
            float buttonWidth = (width - 16 - gap * 2) / 3f;
            for (int i = 0; i < actions.Length; i++)
            {
                int row = i / 3;
                int col = i % 3;
                Rect rect = new Rect(8 + col * (buttonWidth + gap), 86 + row * 96, buttonWidth, 72);
                DrawPanel(rect, false);
                GUI.Button(new Rect(rect.x + 10, rect.y + 16, rect.width - 20, 40), actions[i], _buttonStyle);
            }
        }

        private void DrawFooter()
        {
            DrawRect(new Rect(212, _window.height - 36, _window.width - 212, 1), new Color(0.65f, 0.02f, 0.04f, 0.28f));
            GUI.Label(new Rect(232, _window.height - 29, 360, 18), "ASGARD SERVER SUITE 7.0.6  //  CRIMSON VOID", _footerStyle);
            GUI.Label(new Rect(_window.width - 390, _window.height - 29, 360, 18), "INTERFAZ LOCAL • ACCIONES VERIFICADAS EN SERVIDOR", _footerStyle);
        }

        private void DrawEmergencyPanel()
        {
            EnsureTheme();
            Rect rect = new Rect(30, 30, 650, 180);
            GUI.DrawTexture(rect, _voidTexture);
            DrawOutline(rect, Crimson, 2f);
            GUI.Label(new Rect(52, 50, 580, 30), "ASGARD UI — MODO DE PROTECCIÓN", _sectionStyle);
            GUI.Label(new Rect(52, 88, 580, 48), _lastGuiError, _bodyStyle);
            if (GUI.Button(new Rect(52, 145, 150, 34), "CERRAR PANEL", _dangerButtonStyle)) SetOpen(false);
        }

        private void SendAuditPulse()
        {
            try
            {
                string player = Player.m_localPlayer != null ? Player.m_localPlayer.GetPlayerName() : "admin";
                AsgardCorePlugin.ReportAudit(new AuditEvent
                {
                    event_type = "admin_ui_pulse",
                    player_name = player,
                    evidence = new System.Collections.Generic.Dictionary<string, object>
                    {
                        ["ui_version"] = Version,
                        ["scene"] = UnityEngine.SceneManagement.SceneManager.GetActiveScene().name
                    }
                });
            }
            catch (Exception ex)
            {
                _lastGuiError = "Pulso: " + ex.Message;
                Logger.LogWarning(_lastGuiError);
            }
        }

        private string GetDiagnosticText()
        {
            if (!AsgardCorePlugin.IsReady)
                return "Core no está completamente inicializado. La interfaz seguirá operativa, pero el envío de auditorías permanecerá desconectado.";
            if (AsgardCorePlugin.CurrentBridgeState == "SIN ENLACE")
                return "Core está activo; Host Bridge no respondió. Revisa URL/token o inicia ASGARD Service. El juego permanece estable.";
            return "Todos los módulos locales están listos. Envía un pulso para verificar token, servicio y almacenamiento de auditoría.";
        }

        private static string GetPlayerCount()
        {
            try
            {
                if (ZNet.instance == null) return "0";
                int peers = ZNet.instance.GetPeers() != null ? ZNet.instance.GetPeers().Count : 0;
                return Mathf.Max(1, peers + 1).ToString();
            }
            catch { return "--"; }
        }

        private static string GetConnectionLabel()
        {
            try { return ZNet.instance != null ? "Sesión de red activa" : "Menú / sin sesión"; }
            catch { return "Estado no disponible"; }
        }

        private static Color BridgeColor()
        {
            string status = AsgardCorePlugin.CurrentBridgeState;
            if (status == "ENLACE ACTIVO") return Success;
            if (status == "SIN ENLACE") return Warning;
            return CrimsonSoft;
        }

        private static Color ModeColor()
        {
            string mode = AsgardCorePlugin.CurrentMode.ToLowerInvariant();
            if (mode == "automatic") return Crimson;
            if (mode == "manual") return Warning;
            if (mode == "observe") return Success;
            return TextMuted;
        }

        private static string Trim(string value, int max)
        {
            if (string.IsNullOrEmpty(value)) return "--";
            return value.Length <= max ? value : value.Substring(0, max - 1) + "…";
        }

        private void DrawRect(Rect rect, Color color)
        {
            Color previous = GUI.color;
            GUI.color = color;
            GUI.DrawTexture(rect, Texture2D.whiteTexture);
            GUI.color = previous;
        }

        private void DrawOutline(Rect rect, Color color, float thickness)
        {
            DrawRect(new Rect(rect.x, rect.y, rect.width, thickness), color);
            DrawRect(new Rect(rect.x, rect.yMax - thickness, rect.width, thickness), color);
            DrawRect(new Rect(rect.x, rect.y, thickness, rect.height), color);
            DrawRect(new Rect(rect.xMax - thickness, rect.y, thickness, rect.height), color);
        }

        private void DrawCircle(Vector2 center, float radius, Color color, float thickness, int segments)
        {
            Vector2 previous = center + new Vector2(radius, 0);
            for (int i = 1; i <= segments; i++)
            {
                float angle = i * Mathf.PI * 2f / segments;
                Vector2 next = center + new Vector2(Mathf.Cos(angle) * radius, Mathf.Sin(angle) * radius);
                DrawLine(previous, next, color, thickness);
                previous = next;
            }
        }

        private void DrawLine(Vector2 start, Vector2 end, Color color, float width)
        {
            Matrix4x4 matrix = GUI.matrix;
            Color previous = GUI.color;
            float angle = Vector3.Angle(end - start, Vector2.right);
            if (start.y > end.y) angle = -angle;
            GUI.color = color;
            GUIUtility.RotateAroundPivot(angle, start);
            GUI.DrawTexture(new Rect(start.x, start.y - width * 0.5f, (end - start).magnitude, width), Texture2D.whiteTexture);
            GUI.matrix = matrix;
            GUI.color = previous;
        }
    }
}
