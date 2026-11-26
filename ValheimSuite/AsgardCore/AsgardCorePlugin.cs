using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using UnityEngine;

namespace Asgard.Core
{
    [BepInPlugin(Guid, Name, Version)]
    public sealed class AsgardCorePlugin : BaseUnityPlugin
    {
        public const string Guid = "com.asgard.server.core";
        public const string Name = "ASGARD Server Core";
        public const string Version = "7.0.6";
        public const string BuildLabel = "Crimson Void R6";

        internal static AsgardCorePlugin Instance;
        public static ManualLogSource Log { get; private set; }
        public static ConfigEntry<int> ServerId { get; private set; }
        public static ConfigEntry<string> BridgeUrl { get; private set; }
        public static ConfigEntry<string> BridgeToken { get; private set; }
        public static ConfigEntry<string> EnforcementMode { get; private set; }
        public static ConfigEntry<bool> RequireExactIdentity { get; private set; }
        public static ConfigEntry<int> AutomaticThreshold { get; private set; }
        public static BridgeClient Bridge { get; private set; }
        public static event Action<Violation> ViolationConfirmed;

        public static bool IsReady => Instance != null && Bridge != null;
        public static int CurrentServerId => ServerId != null ? ServerId.Value : 0;
        public static string CurrentMode => EnforcementMode != null ? EnforcementMode.Value : "offline";
        public static string CurrentBridgeState => Bridge != null ? Bridge.Status : "CORE DESCONECTADO";
        public static string CurrentBridgeDetail => Bridge != null ? Bridge.StatusDetail : "AsgardCore no terminó de inicializarse.";

        private void Awake()
        {
            Instance = this;
            Log = Logger;
            ServerId = Config.Bind("Bridge", "ServerId", 1, "ID del servidor dentro de ASGARD Host Manager.");
            BridgeUrl = Config.Bind("Bridge", "Url", "http://127.0.0.1:8765", "Servicio ASGARD local.");
            BridgeToken = Config.Bind("Bridge", "Token", "CAMBIAR", "Token mostrado en ASGARD Suite.");
            EnforcementMode = Config.Bind("Enforcement", "Mode", "observe", "observe, manual o automatic.");
            RequireExactIdentity = Config.Bind("Enforcement", "RequireExactIdentity", true, "Nunca auto-banea sin Platform ID exacto.");
            AutomaticThreshold = Config.Bind("Enforcement", "AutomaticThreshold", 100, "Severidad mínima para castigo automático.");
            Bridge = new BridgeClient(BridgeUrl.Value.TrimEnd('/'), ServerId.Value, BridgeToken.Value, Logger);
            Logger.LogInfo($"ASGARD Core {Version} ({BuildLabel}) activo. Modo={EnforcementMode.Value}");
        }

        private void OnDestroy()
        {
            if (ReferenceEquals(Instance, this)) Instance = null;
        }

        public static void ReportAudit(AuditEvent evt)
        {
            if (evt == null) return;
            Bridge?.PostAudit(evt);
        }

        public static void ReportViolation(Violation violation)
        {
            if (violation == null) return;
            ReportAudit(violation.ToAuditEvent());
            string mode = CurrentMode.ToLowerInvariant();
            bool exact = !string.IsNullOrWhiteSpace(violation.PlatformId);
            int threshold = AutomaticThreshold != null ? AutomaticThreshold.Value : 100;
            bool requireExact = RequireExactIdentity == null || RequireExactIdentity.Value;
            if (mode == "automatic" && violation.Severity >= threshold && (!requireExact || exact))
            {
                ViolationConfirmed?.Invoke(violation);
            }
            else
            {
                Log?.LogWarning($"Violación registrada sin castigo automático: {violation.Code}, sev={violation.Severity}, exact={exact}, mode={mode}");
            }
        }
    }

    [Serializable]
    public sealed class AuditEvent
    {
        public string event_type = "unknown";
        public int severity;
        public string player_name = "";
        public string platform_id = "";
        public string prefab = "";
        public Dictionary<string, object> position = new Dictionary<string, object>();
        public Dictionary<string, object> evidence = new Dictionary<string, object>();
        public double created_unix = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
    }

    [Serializable]
    public sealed class Violation
    {
        public string Code = "unknown";
        public int Severity = 100;
        public string PlayerName = "";
        public string PlatformId = "";
        public string Reason = "Regla crítica";
        public Player Player;
        public Dictionary<string, object> Evidence = new Dictionary<string, object>();

        public AuditEvent ToAuditEvent()
        {
            return new AuditEvent
            {
                event_type = "violation:" + Code,
                severity = Severity,
                player_name = PlayerName,
                platform_id = PlatformId,
                evidence = Evidence ?? new Dictionary<string, object>()
            };
        }
    }

    public sealed class BridgeClient
    {
        private readonly string _baseUrl;
        private readonly int _serverId;
        private readonly string _token;
        private readonly ManualLogSource _log;
        private volatile string _status = "EN ESPERA";
        private volatile string _statusDetail = "Aún no se ha enviado ningún evento.";

        public string Status => _status;
        public string StatusDetail => _statusDetail;

        public BridgeClient(string baseUrl, int serverId, string token, ManualLogSource log)
        {
            _baseUrl = baseUrl;
            _serverId = serverId;
            _token = token;
            _log = log;
        }

        public void PostAudit(AuditEvent evt) => PostAsync($"/asgard-suite/{_serverId}/audit", evt);

        public void QueuePunishment(Violation violation, string avatarMode, bool ban)
        {
            var payload = new Dictionary<string, object>
            {
                ["platform_id"] = violation != null ? violation.PlatformId : "",
                ["player_name"] = violation != null ? violation.PlayerName : "",
                ["reason"] = violation != null ? violation.Reason : "",
                ["severity"] = violation != null ? violation.Severity : 0,
                ["avatar_mode"] = avatarMode ?? "vanilla",
                ["ban"] = ban
            };
            PostAsync($"/asgard-suite/{_serverId}/punishments", payload);
        }

        public void PostAdminAction(string action, object payload)
        {
            PostAsync($"/asgard-suite/{_serverId}/audit", new AuditEvent
            {
                event_type = "admin:" + (action ?? "unknown"),
                severity = 0,
                evidence = new Dictionary<string, object> { ["payload"] = payload }
            });
        }

        private void PostAsync(string path, object payload)
        {
            ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    byte[] body = Encoding.UTF8.GetBytes(AsgardJson.Serialize(payload));
                    var request = (HttpWebRequest)WebRequest.Create(_baseUrl + path);
                    request.Method = "POST";
                    request.ContentType = "application/json";
                    request.Timeout = 8000;
                    request.ReadWriteTimeout = 8000;
                    request.Headers["X-Asgard-Token"] = _token;
                    request.ContentLength = body.Length;
                    using (var stream = request.GetRequestStream()) stream.Write(body, 0, body.Length);
                    using (var response = (HttpWebResponse)request.GetResponse())
                    {
                        if ((int)response.StatusCode >= 300) throw new InvalidOperationException(response.StatusCode.ToString());
                    }
                    _status = "ENLACE ACTIVO";
                    _statusDetail = "Último envío correcto: " + DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture);
                }
                catch (Exception ex)
                {
                    _status = "SIN ENLACE";
                    _statusDetail = ex.Message;
                    _log?.LogWarning("Bridge ASGARD: " + ex.Message);
                }
            });
        }
    }

    internal static class AsgardJson
    {
        public static string Serialize(object value)
        {
            var builder = new StringBuilder(256);
            WriteValue(builder, value, 0, new HashSet<object>(ReferenceComparer.Instance));
            return builder.ToString();
        }

        private static void WriteValue(StringBuilder builder, object value, int depth, HashSet<object> visited)
        {
            if (value == null) { builder.Append("null"); return; }
            if (depth > 16) { WriteString(builder, "<max-depth>"); return; }

            if (value is string text) { WriteString(builder, text); return; }
            if (value is char character) { WriteString(builder, character.ToString()); return; }
            if (value is bool boolean) { builder.Append(boolean ? "true" : "false"); return; }
            if (value is Enum) { WriteString(builder, value.ToString()); return; }
            if (IsNumber(value)) { builder.Append(Convert.ToString(value, CultureInfo.InvariantCulture)); return; }
            if (value is DateTime dateTime) { WriteString(builder, dateTime.ToUniversalTime().ToString("o", CultureInfo.InvariantCulture)); return; }
            if (value is DateTimeOffset offset) { WriteString(builder, offset.ToUniversalTime().ToString("o", CultureInfo.InvariantCulture)); return; }

            Type type = value.GetType();
            bool track = !type.IsValueType;
            if (track && !visited.Add(value)) { WriteString(builder, "<cycle>"); return; }
            try
            {
                if (value is IDictionary dictionary)
                {
                    WriteDictionary(builder, dictionary, depth, visited);
                    return;
                }
                if (value is IEnumerable enumerable)
                {
                    WriteArray(builder, enumerable, depth, visited);
                    return;
                }
                WriteObject(builder, value, depth, visited);
            }
            finally
            {
                if (track) visited.Remove(value);
            }
        }

        private static void WriteDictionary(StringBuilder builder, IDictionary dictionary, int depth, HashSet<object> visited)
        {
            builder.Append('{');
            bool first = true;
            foreach (DictionaryEntry entry in dictionary)
            {
                if (!first) builder.Append(',');
                first = false;
                WriteString(builder, Convert.ToString(entry.Key, CultureInfo.InvariantCulture) ?? "");
                builder.Append(':');
                WriteValue(builder, entry.Value, depth + 1, visited);
            }
            builder.Append('}');
        }

        private static void WriteArray(StringBuilder builder, IEnumerable enumerable, int depth, HashSet<object> visited)
        {
            builder.Append('[');
            bool first = true;
            foreach (object item in enumerable)
            {
                if (!first) builder.Append(',');
                first = false;
                WriteValue(builder, item, depth + 1, visited);
            }
            builder.Append(']');
        }

        private static void WriteObject(StringBuilder builder, object value, int depth, HashSet<object> visited)
        {
            builder.Append('{');
            bool first = true;
            Type type = value.GetType();
            foreach (FieldInfo field in type.GetFields(BindingFlags.Instance | BindingFlags.Public))
            {
                if (field.IsNotSerialized || typeof(UnityEngine.Object).IsAssignableFrom(field.FieldType)) continue;
                if (!first) builder.Append(',');
                first = false;
                WriteString(builder, field.Name);
                builder.Append(':');
                WriteValue(builder, field.GetValue(value), depth + 1, visited);
            }
            foreach (PropertyInfo property in type.GetProperties(BindingFlags.Instance | BindingFlags.Public))
            {
                if (!property.CanRead || property.GetIndexParameters().Length != 0 || typeof(UnityEngine.Object).IsAssignableFrom(property.PropertyType)) continue;
                object propertyValue;
                try { propertyValue = property.GetValue(value, null); }
                catch { continue; }
                if (!first) builder.Append(',');
                first = false;
                WriteString(builder, property.Name);
                builder.Append(':');
                WriteValue(builder, propertyValue, depth + 1, visited);
            }
            builder.Append('}');
        }

        private static bool IsNumber(object value)
        {
            return value is byte || value is sbyte || value is short || value is ushort || value is int || value is uint ||
                   value is long || value is ulong || value is float || value is double || value is decimal;
        }

        private static void WriteString(StringBuilder builder, string value)
        {
            builder.Append('"');
            if (value != null)
            {
                foreach (char c in value)
                {
                    switch (c)
                    {
                        case '"': builder.Append("\\\""); break;
                        case '\\': builder.Append("\\\\"); break;
                        case '\b': builder.Append("\\b"); break;
                        case '\f': builder.Append("\\f"); break;
                        case '\n': builder.Append("\\n"); break;
                        case '\r': builder.Append("\\r"); break;
                        case '\t': builder.Append("\\t"); break;
                        default:
                            if (c < 32) builder.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                            else builder.Append(c);
                            break;
                    }
                }
            }
            builder.Append('"');
        }

        private sealed class ReferenceComparer : IEqualityComparer<object>
        {
            public static readonly ReferenceComparer Instance = new ReferenceComparer();
            public new bool Equals(object x, object y) => ReferenceEquals(x, y);
            public int GetHashCode(object obj) => System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(obj);
        }
    }

    public static class IdentityResolver
    {
        public static void Resolve(Player player, out string name, out string platformId)
        {
            name = player != null ? player.GetPlayerName() : "";
            platformId = "";
            if (player == null || ZNet.instance == null) return;
            try
            {
                long playerId = player.GetPlayerID();
                foreach (var peer in ZNet.instance.GetPeers())
                {
                    if (peer == null || peer.m_uid != playerId) continue;
                    name = string.IsNullOrWhiteSpace(peer.m_playerName) ? name : peer.m_playerName;
                    platformId = peer.m_socket != null ? peer.m_socket.GetHostName() : "";
                    break;
                }
            }
            catch (Exception ex)
            {
                AsgardCorePlugin.Log?.LogDebug("Identidad parcial: " + ex.Message);
            }
        }
    }
}
