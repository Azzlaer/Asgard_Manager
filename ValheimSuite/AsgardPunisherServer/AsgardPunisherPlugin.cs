using System;
using System.Collections;
using System.Linq;
using System.Reflection;
using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;
using Asgard.Core;

namespace Asgard.Punisher
{
    [BepInPlugin(Guid, Name, Version)]
    [BepInProcess("valheim_server.exe")]
    [BepInDependency(AsgardCorePlugin.Guid)]
    public sealed class AsgardPunisherPlugin : BaseUnityPlugin
    {
        public const string Guid="com.asgard.server.punisher"; public const string Name="ASGARD Anticheat Encarnado"; public const string Version = "7.0.6";
        internal static AsgardPunisherPlugin Instance;
        internal static ConfigEntry<string> Mode, VanillaPrefabs; internal static ConfigEntry<float> Delay, Distance; internal static ConfigEntry<bool> BanAfterExecution, CollateralDamage;
        private Harmony _harmony;
        private void Awake()
        {
            Instance=this;
            Mode=Config.Bind("Avatar","Mode","vanilla","vanilla o enhanced. Enhanced requiere AsgardVoidAvatarClient en todos los clientes.");
            VanillaPrefabs=Config.Bind("Avatar","VanillaPrefabFallbacks","Fader,SeekerQueen,GoblinKing,Bonemass","Primer prefab existente se usa como encarnación vanilla.");
            Delay=Config.Bind("Avatar","ExecutionDelay",4.5f,"Segundos cinematográficos antes del golpe.");
            Distance=Config.Bind("Avatar","SpawnDistance",12f,"Distancia de aparición.");
            BanAfterExecution=Config.Bind("Punishment","BanAfterExecution",true,"Añade Platform ID a bannedlist mediante Host Manager.");
            CollateralDamage=Config.Bind("Punishment","CollateralDamage",false,"Desactivado evita usar el avatar como arma de griefing contra construcciones.");
            AsgardCorePlugin.ViolationConfirmed += Execute;
            _harmony=new Harmony(Guid);_harmony.PatchAll();
            Logger.LogWarning("Anticheat Encarnado preparado. Verifica identidad y modo antes de activar automatic.");
        }
        private void OnDestroy(){AsgardCorePlugin.ViolationConfirmed-=Execute;_harmony?.UnpatchSelf();}
        private void Execute(Violation violation)
        {
            if(violation?.Player==null){Logger.LogWarning("Castigo omitido: no hay Player vivo asociado.");return;}
            StartCoroutine(Sequence(violation));
        }
        private IEnumerator Sequence(Violation v)
        {
            Player target=v.Player; Vector3 forward=target.transform.forward; Vector3 pos=target.transform.position+forward*Distance.Value+Vector3.up*1.5f;
            GameObject prefab=ResolvePrefab();
            GameObject avatar=prefab!=null?Instantiate(prefab,pos,Quaternion.LookRotation(-forward)):null;
            if(avatar!=null){avatar.name="ASGARD_ANTICHEAT_ENCARNADO";avatar.AddComponent<AvatarMarker>();var c=avatar.GetComponent<Character>();if(c!=null){c.m_name="$asgard_void_avatar";c.SetHealth(1000000000f);}}
            Broadcast($"<color=#22D3EE>ASGARD</color>: infracción crítica confirmada para {v.PlayerName}. El vacío ha respondido.");
            yield return new WaitForSeconds(Mathf.Max(1f,Delay.Value));
            KillTarget(target,avatar);
            AsgardCorePlugin.Bridge.QueuePunishment(v, Mode.Value, BanAfterExecution.Value);
            yield return new WaitForSeconds(2f);
            if(avatar!=null) Destroy(avatar);
        }
        private GameObject ResolvePrefab()
        {
            if(ZNetScene.instance==null) return null;
            if(Mode.Value.Equals("enhanced",StringComparison.OrdinalIgnoreCase))
            {
                var enhanced=ZNetScene.instance.GetPrefab("AsgardVoidAvatar"); if(enhanced!=null) return enhanced;
            }
            foreach(string raw in VanillaPrefabs.Value.Split(',')){var p=ZNetScene.instance.GetPrefab(raw.Trim());if(p!=null)return p;}
            return null;
        }
        private static void KillTarget(Player target,GameObject avatar)
        {
            if(target==null)return;
            try{var hit=new HitData();hit.m_damage.m_damage=1000000f;hit.m_point=target.transform.position;hit.m_dir=(target.transform.position-(avatar?avatar.transform.position:target.transform.position-Vector3.forward)).normalized;var attacker=avatar?avatar.GetComponent<Character>():null;if(attacker!=null)hit.SetAttacker(attacker);target.Damage(hit);}catch{var mi=AccessTools.Method(typeof(Character),"SetHealth");mi?.Invoke(target,new object[]{0f});}
        }
        private static void Broadcast(string text)
        {
            try{MessageHud.instance?.ShowMessage(MessageHud.MessageType.Center,text);}catch{}
            AsgardCorePlugin.Log?.LogWarning(text);
        }
    }
    public sealed class AvatarMarker:MonoBehaviour{}
    [HarmonyPatch(typeof(Character),nameof(Character.Damage))]
    internal static class ImmortalAvatarPatch{static bool Prefix(Character __instance)=>__instance==null||__instance.GetComponent<AvatarMarker>()==null;}
}
