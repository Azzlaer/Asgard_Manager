using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;
using Asgard.Core;

namespace Asgard.Audit
{
    [BepInPlugin(Guid, Name, Version)]
    [BepInProcess("valheim_server.exe")]
    [BepInDependency(AsgardCorePlugin.Guid)]
    public sealed class AsgardAuditPlugin : BaseUnityPlugin
    {
        public const string Guid="com.asgard.server.audit"; public const string Name="ASGARD Audit"; public const string Version = "7.0.6";
        internal static ConfigEntry<int> DamageBurstThreshold; internal static ConfigEntry<float> DamageWindow; internal static ConfigEntry<bool> ObserveTerrain;
        private Harmony _harmony;
        private void Awake()
        {
            DamageBurstThreshold=Config.Bind("Detection","StructureDamageEvents",35,"Eventos de daño a estructuras dentro de la ventana antes de elevar una violación.");
            DamageWindow=Config.Bind("Detection","StructureDamageWindowSeconds",5f,"Ventana del detector.");
            ObserveTerrain=Config.Bind("Audit","Terrain",true,"Auditar modificaciones de terreno.");
            _harmony=new Harmony(Guid); _harmony.PatchAll(); Logger.LogInfo("ASGARD Audit activo.");
        }
        private void OnDestroy(){_harmony?.UnpatchSelf();}
    }

    internal static class AuditRuntime
    {
        private static readonly Dictionary<long, Queue<float>> DamageTimes = new Dictionary<long, Queue<float>>();
        public static void PieceCreated(Piece piece)
        {
            if(piece==null) return; var player=Player.m_localPlayer; string name,id; IdentityResolver.Resolve(player,out name,out id);
            AsgardCorePlugin.ReportAudit(new AuditEvent{event_type="piece_created",player_name=name,platform_id=id,prefab=piece.gameObject.name,position=Pos(piece.transform.position)});
        }
        public static void StructureDamaged(WearNTear wnt)
        {
            if(wnt==null) return; var player=Player.m_localPlayer; string name,id; IdentityResolver.Resolve(player,out name,out id);
            AsgardCorePlugin.ReportAudit(new AuditEvent{event_type="structure_damage",severity=20,player_name=name,platform_id=id,prefab=wnt.gameObject.name,position=Pos(wnt.transform.position)});
            if(player==null) return; long key=player.GetPlayerID(); float now=Time.time;
            if(!DamageTimes.TryGetValue(key,out var q)){q=new Queue<float>();DamageTimes[key]=q;} q.Enqueue(now);
            while(q.Count>0 && now-q.Peek()>AsgardAuditPlugin.DamageWindow.Value) q.Dequeue();
            if(q.Count>=AsgardAuditPlugin.DamageBurstThreshold.Value){q.Clear();AsgardCorePlugin.ReportViolation(new Violation{Code="structure_damage_burst",Severity=100,Player=player,PlayerName=name,PlatformId=id,Reason="Ráfaga anormal de daño a estructuras",Evidence=new Dictionary<string,object>{{"window",AsgardAuditPlugin.DamageWindow.Value},{"events",AsgardAuditPlugin.DamageBurstThreshold.Value}}});}
        }
        public static void StructureDestroyed(WearNTear wnt)
        {
            if(wnt==null) return; var player=Player.m_localPlayer; string name,id; IdentityResolver.Resolve(player,out name,out id);
            AsgardCorePlugin.ReportAudit(new AuditEvent{event_type="structure_destroyed",severity=50,player_name=name,platform_id=id,prefab=wnt.gameObject.name,position=Pos(wnt.transform.position)});
        }
        private static Dictionary<string,object> Pos(Vector3 p)=>new Dictionary<string,object>{{"x",p.x},{"y",p.y},{"z",p.z}};
    }

    [HarmonyPatch(typeof(Piece), nameof(Piece.SetCreator))]
    internal static class PieceCreatorPatch { private static void Postfix(Piece __instance)=>AuditRuntime.PieceCreated(__instance); }
    [HarmonyPatch(typeof(WearNTear), nameof(WearNTear.Damage))]
    internal static class WearDamagePatch { private static void Postfix(WearNTear __instance)=>AuditRuntime.StructureDamaged(__instance); }
    [HarmonyPatch]
    internal static class WearDestroyPatch
    {
        static MethodBase TargetMethod()=>AccessTools.Method(typeof(WearNTear),"Destroy");
        static void Prefix(WearNTear __instance)=>AuditRuntime.StructureDestroyed(__instance);
    }
}
