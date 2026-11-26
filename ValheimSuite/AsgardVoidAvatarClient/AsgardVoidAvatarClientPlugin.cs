using System;
using BepInEx;
using Jotunn.Configs;
using Jotunn.Entities;
using Jotunn.Managers;
using UnityEngine;

namespace Asgard.VoidAvatar
{
    [BepInPlugin(Guid,Name,Version)]
    [BepInDependency(Jotunn.Main.ModGuid)]
    public sealed class VoidAvatarPlugin:BaseUnityPlugin
    {
        public const string Guid="com.asgard.client.voidavatar";public const string Name="ASGARD Void Avatar Client";public const string Version = "7.0.6";
        private void Awake(){CreatureManager.OnVanillaCreaturesAvailable+=Register;}
        private void Register()
        {
            try
            {
                string baseName=ChooseBase();
                var custom=new CustomCreature("AsgardVoidAvatar",baseName,new CreatureConfig());
                var root=custom.Prefab;root.transform.localScale*=1.65f;
                foreach(var renderer in root.GetComponentsInChildren<Renderer>(true))
                {
                    var mats=renderer.materials;
                    for(int i=0;i<mats.Length;i++){var m=new Material(mats[i]);if(m.HasProperty("_Color"))m.color=new Color(.035f,.005f,.08f,1f);if(m.HasProperty("_EmissionColor")){m.EnableKeyword("_EMISSION");m.SetColor("_EmissionColor",new Color(.3f,0f,1.4f)*3f);}mats[i]=m;}
                    renderer.materials=mats;
                }
                AddVoidLight(root,new Color(.4f,.05f,1f),7f,18f,Vector3.up*4f);
                AddVoidLight(root,new Color(0f,.8f,1f),5f,12f,Vector3.up*8f);
                AddParticles(root);
                CreatureManager.Instance.AddCreature(custom);
                Logger.LogInfo("AsgardVoidAvatar registrado desde "+baseName);
            }
            catch(Exception ex){Logger.LogError("No se pudo registrar Void Avatar: "+ex);}
            CreatureManager.OnVanillaCreaturesAvailable-=Register;
        }
        private static string ChooseBase(){foreach(string n in new[]{"Fader","SeekerQueen","GoblinKing","Bonemass"})if(CreatureManager.Instance.GetCreaturePrefab(n)!=null)return n;return "Troll";}
        private static void AddVoidLight(GameObject root,Color color,float intensity,float range,Vector3 offset){var go=new GameObject("ASGARD_VoidLight");go.transform.SetParent(root.transform,false);go.transform.localPosition=offset;var l=go.AddComponent<Light>();l.type=LightType.Point;l.color=color;l.intensity=intensity;l.range=range;}
        private static void AddParticles(GameObject root)
        {
            var go=new GameObject("ASGARD_VoidParticles");go.transform.SetParent(root.transform,false);go.transform.localPosition=Vector3.up*3f;
            var ps=go.AddComponent<ParticleSystem>();var main=ps.main;main.loop=true;main.startLifetime=2.5f;main.startSpeed=.6f;main.startSize=.35f;main.maxParticles=450;main.startColor=new ParticleSystem.MinMaxGradient(new Color(.55f,.1f,1f,.8f),new Color(0f,.9f,1f,.8f));
            var emission=ps.emission;emission.rateOverTime=90f;var shape=ps.shape;shape.shapeType=ParticleSystemShapeType.Sphere;shape.radius=4f;var renderer=ps.GetComponent<ParticleSystemRenderer>();renderer.renderMode=ParticleSystemRenderMode.Billboard;
        }
    }
}
