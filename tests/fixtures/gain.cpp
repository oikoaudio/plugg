// SPDX-License-Identifier: GPL-3.0-or-later
// Minimal freestanding Windows VST3 fixture. No Wine or vendor SDK runtime.
// ABI declarations match the published VST3 interfaces. Not a product plug-in.
using i32=int; using u32=unsigned; using u64=unsigned long long; using tbool=unsigned char;
using uid=const char*;
inline void* operator new(__SIZE_TYPE__,void* p) { return p; }
extern "C" void* memcpy(void* d,const void* s,__SIZE_TYPE__ n) {for(__SIZE_TYPE__ i=0;i<n;++i)static_cast<char*>(d)[i]=static_cast<const char*>(s)[i];return d;}
extern "C" void* memset(void* d,int c,__SIZE_TYPE__ n) {for(__SIZE_TYPE__ i=0;i<n;++i)static_cast<char*>(d)[i]=c;return d;}
static bool equal(uid a,uid b) {for(int i=0;i<16;++i)if(a[i]!=b[i])return false;return true;}
static void text(char* d,const char* s) {while((*d++=*s++)) {}}
static constexpr i32 nointerface=static_cast<i32>(0x80004002u);
static const char unknown_id[16]={0,0,0,0,0,0,0,0,static_cast<char>(0xc0),0,0,0,0,0,0,0x46};
static const unsigned char component_bytes[16]={0x31,0xff,0x31,0xe8,0xd5,0xf2,0x01,0x43,0x92,0x8e,0xbb,0xee,0x25,0x69,0x78,0x02};
static const unsigned char base_bytes[16]={0xdb,0x8d,0x88,0x22,0x6e,0x15,0xae,0x45,0x83,0x58,0xb3,0x48,0x08,0x19,0x06,0x25};
static const unsigned char audio_bytes[16]={0x99,0x3f,0x04,0x42,0xda,0xb7,0x3c,0x45,0xa5,0x69,0xe7,0x9d,0x9a,0xae,0xc3,0x3d};
static const unsigned char factory_bytes[16]={0x1c,0x81,0x4d,0x7a,0x11,0x52,0x1f,0x4a,0xae,0xd9,0xd2,0xee,0x0b,0x43,0xbf,0x9f};
static const char class_id[16]={'P','H','O','S','T','G','A','I','N','T','E','S','T','0','0','1'};
struct Unknown {virtual i32 queryInterface(uid,void**)=0;virtual u32 addRef()=0;virtual u32 release()=0;};
struct BusInfo {i32 mediaType,direction,channelCount;unsigned short name[128];i32 busType;u32 flags;};
struct RoutingInfo {i32 mediaType,busIndex,channel;};
struct Setup {i32 processMode,symbolicSampleSize,maxSamplesPerBlock;double sampleRate;};
struct Buffers {i32 numChannels;u64 silenceFlags;union {float** f32;double** f64;};};
struct Data {i32 processMode,symbolicSampleSize,numSamples,numInputs,numOutputs;Buffers* inputs;Buffers* outputs;void* rest[5];};
struct Component : Unknown {
 virtual i32 initialize(Unknown*)=0;virtual i32 terminate()=0;virtual i32 getControllerClassId(char*)=0;
 virtual i32 setIoMode(i32)=0;virtual i32 getBusCount(i32,i32)=0;virtual i32 getBusInfo(i32,i32,i32,BusInfo&)=0;
 virtual i32 getRoutingInfo(RoutingInfo&,RoutingInfo&)=0;virtual i32 activateBus(i32,i32,i32,tbool)=0;
 virtual i32 setActive(tbool)=0;virtual i32 setState(void*)=0;virtual i32 getState(void*)=0;
};
struct Processor : Unknown {
 virtual i32 setBusArrangements(u64*,i32,u64*,i32)=0;virtual i32 getBusArrangement(i32,i32,u64&)=0;
 virtual i32 canProcessSampleSize(i32)=0;virtual u32 getLatencySamples()=0;virtual i32 setupProcessing(Setup&)=0;
 virtual i32 setProcessing(tbool)=0;virtual i32 process(Data&)=0;virtual u32 getTailSamples()=0;
};
struct Effect : Component,Processor {
 u32 refs=1;bool used=false;
 i32 queryInterface(uid id,void** out) override {
  *out=nullptr;
  if(equal(id,reinterpret_cast<const char*>(component_bytes))||equal(id,unknown_id)||equal(id,reinterpret_cast<const char*>(base_bytes)))*out=static_cast<Component*>(this);
  else if(equal(id,reinterpret_cast<const char*>(audio_bytes)))*out=static_cast<Processor*>(this);
  else return nointerface;
  addRef();return 0;
 }
 u32 addRef() override{return ++refs;} u32 release() override{if(refs>0)--refs;if(!refs)used=false;return refs;}
 i32 initialize(Unknown*) override{return 0;} i32 terminate() override{return 0;}
 i32 getControllerClassId(char* id) override{memset(id,0,16);return 1;}
 i32 setIoMode(i32) override{return 0;} i32 getBusCount(i32 type,i32) override{return type==0?1:0;}
 i32 getBusInfo(i32 type,i32 dir,i32 index,BusInfo& info) override {
  if(type!=0||index!=0)return 1;memset(&info,0,sizeof(info));info.mediaType=type;info.direction=dir;info.channelCount=2;info.flags=1;return 0;
 }
 i32 getRoutingInfo(RoutingInfo&,RoutingInfo&) override{return 1;}
 i32 activateBus(i32,i32,i32,tbool) override{return 0;} i32 setActive(tbool) override{return 0;}
 i32 setState(void*) override{return 0;} i32 getState(void*) override{return 0;}
 i32 setBusArrangements(u64* in,i32 ni,u64* out,i32 no) override{return ni==1&&no==1&&in[0]==3&&out[0]==3?0:1;}
 i32 getBusArrangement(i32,i32 index,u64& arr) override{arr=3;return index==0?0:1;}
 i32 canProcessSampleSize(i32 size) override{return size==0?0:1;}u32 getLatencySamples() override{return 0;}
 i32 setupProcessing(Setup& setup) override{return setup.symbolicSampleSize==0?0:1;}i32 setProcessing(tbool) override{return 0;}
 i32 process(Data& data) override{
  if(data.symbolicSampleSize!=0)return 1;
  if(data.numInputs==0||data.numOutputs==0)return 0;
  for(int c=0;c<data.outputs[0].numChannels;++c)for(int s=0;s<data.numSamples;++s)data.outputs[0].f32[c][s]=(c<data.inputs[0].numChannels?data.inputs[0].f32[c][s]*0.5f:0.f);
  data.outputs[0].silenceFlags=0;return 0;
 }u32 getTailSamples() override{return 0;}
};
struct FactoryInfo {char vendor[64],url[256],email[128];i32 flags;};
struct ClassInfo {char cid[16];i32 cardinality;char category[32],name[64];};
alignas(16) static unsigned char effects[16][sizeof(Effect)];
static bool initialized=false;
struct Factory : Unknown {
 i32 queryInterface(uid id,void** out) override{*out=nullptr;if(equal(id,unknown_id)||equal(id,reinterpret_cast<const char*>(factory_bytes))){*out=this;return 0;}return nointerface;}
 u32 addRef() override{return 1;}u32 release() override{return 1;}
 virtual i32 getFactoryInfo(FactoryInfo* info){memset(info,0,sizeof(*info));text(info->vendor,"Plugg Tests");return 0;}
 virtual i32 countClasses(){return 1;}
 virtual i32 getClassInfo(i32 i,ClassInfo* info){if(i)return 1;memset(info,0,sizeof(*info));memcpy(info->cid,class_id,16);info->cardinality=0x7fffffff;text(info->category,"Audio Module Class");text(info->name,"Plugg Test Gain");return 0;}
 virtual i32 createInstance(uid cid,uid iid,void** out){
  *out=nullptr;if(!equal(cid,class_id))return 1;
  if(!initialized){for(int i=0;i<16;++i)new(effects[i]) Effect;initialized=true;}
  for(int i=0;i<16;++i){auto* e=reinterpret_cast<Effect*>(effects[i]);if(!e->used){e->used=true;e->refs=1;auto r=e->queryInterface(iid,out);e->release();return r;}}
  return 1;
 }
};
extern "C" __declspec(dllexport) void* GetPluginFactory(){alignas(16) static unsigned char bytes[sizeof(Factory)];static bool ready=false;if(!ready){new(bytes)Factory;ready=true;}return bytes;}
extern "C" __declspec(dllexport) bool InitDll(){return true;}
extern "C" __declspec(dllexport) bool ExitDll(){return true;}
extern "C" int DllMain(void*,unsigned,void*){return 1;}

extern "C" { int _fltused=0; int _purecall(){return 0;} }
