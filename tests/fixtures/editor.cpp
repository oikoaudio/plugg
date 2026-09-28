// SPDX-License-Identifier: GPL-3.0-or-later
// Freestanding Windows VST3 fixture with an edit controller and an editor.
// The processor halves its input, like gain.cpp. The editor is a plain Win32
// child window painted one solid colour; a left click reports where it
// landed, in the editor's own coordinates, through three parameters:
//   0 "Click X"  = x / 4096     1 "Click Y" = y / 4096     2 "Clicks" = count / 1000
// A test host clicks at a known point and reads them back, which shows both
// that the editor is where the host frame is and that input reaches it
// without an offset. ABI declarations match the published VST3 interfaces.
//
// Built with -DPLUGG_FIXTURE_ENDS_MAIN_THREAD it becomes "Plugg Test Crash":
// initialize() ends the thread it is called on, which in the bridge's Windows
// host is the main thread. The process lives on in its other threads, as a
// host does after a stack overflow, and a supervisor has to notice.
using i32=int; using u32=unsigned; using u64=unsigned long long; using tbool=unsigned char;
using i64=long long; using u16=unsigned short; using uid=const char*;
inline void* operator new(__SIZE_TYPE__,void* p) { return p; }
extern "C" void* memcpy(void* d,const void* s,__SIZE_TYPE__ n) {for(__SIZE_TYPE__ i=0;i<n;++i)static_cast<char*>(d)[i]=static_cast<const char*>(s)[i];return d;}
extern "C" void* memset(void* d,int c,__SIZE_TYPE__ n) {for(__SIZE_TYPE__ i=0;i<n;++i)static_cast<char*>(d)[i]=c;return d;}
static bool equal(uid a,uid b) {for(int i=0;i<16;++i)if(a[i]!=b[i])return false;return true;}
static bool same(const char* a,const char* b) {while(*a&&*a==*b){++a;++b;}return *a==*b;}
static void text(char* d,const char* s) {while((*d++=*s++)) {}}
static void wide(u16* d,const char* s) {while((*d++=static_cast<unsigned char>(*s++))) {}}
static constexpr i32 ok=0,no=1,nointerface=static_cast<i32>(0x80004002u);

// Interface IDs, in the byte order Windows builds of the SDK use.
#define IID(name,...) static const unsigned char name[16]={__VA_ARGS__}
IID(unknown_id,0,0,0,0,0,0,0,0,0xc0,0,0,0,0,0,0,0x46);
IID(base_id,0xdb,0x8d,0x88,0x22,0x6e,0x15,0xae,0x45,0x83,0x58,0xb3,0x48,0x08,0x19,0x06,0x25);
IID(component_id,0x31,0xff,0x31,0xe8,0xd5,0xf2,0x01,0x43,0x92,0x8e,0xbb,0xee,0x25,0x69,0x78,0x02);
IID(audio_id,0x99,0x3f,0x04,0x42,0xda,0xb7,0x3c,0x45,0xa5,0x69,0xe7,0x9d,0x9a,0xae,0xc3,0x3d);
IID(factory_id,0x1c,0x81,0x4d,0x7a,0x11,0x52,0x1f,0x4a,0xae,0xd9,0xd2,0xee,0x0b,0x43,0xbf,0x9f);
IID(controller_id,0xe3,0xbb,0xd7,0xdc,0x42,0x77,0x8d,0x44,0xa8,0x74,0xaa,0xcc,0x97,0x9c,0x75,0x9e);
IID(view_id,0x07,0x25,0xc3,0x5b,0x60,0xd0,0xea,0x49,0xa6,0x15,0x1b,0x52,0x2b,0x75,0x5b,0x29);
static uid id(const unsigned char* bytes) {return reinterpret_cast<uid>(bytes);}
#ifdef PLUGG_FIXTURE_ENDS_MAIN_THREAD
#define FIXTURE_NAME "Plugg Test Crash"
static const char processor_class[16]={'P','L','U','G','G','C','R','A','S','H','T','E','S','T','0','P'};
static const char controller_class[16]={'P','L','U','G','G','C','R','A','S','H','T','E','S','T','0','C'};
#else
#define FIXTURE_NAME "Plugg Test Editor"
static const char processor_class[16]={'P','L','U','G','G','E','D','I','T','O','R','T','E','S','T','P'};
static const char controller_class[16]={'P','L','U','G','G','E','D','I','T','O','R','T','E','S','T','C'};
#endif

// The few Win32 calls the editor needs.
using HWND=void*; using LRESULT=i64; using WPARAM=u64; using LPARAM=i64;
using WNDPROC=LRESULT(*)(HWND,u32,WPARAM,LPARAM);
struct WNDCLASSW {u32 style;WNDPROC proc;i32 clsExtra,wndExtra;void *instance,*icon,*cursor,*background;const u16 *menu,*name;};
extern "C" {
__declspec(dllimport) u16 RegisterClassW(const WNDCLASSW*);
__declspec(dllimport) HWND CreateWindowExW(u32,const u16*,const u16*,u32,i32,i32,i32,i32,HWND,void*,void*,void*);
__declspec(dllimport) i32 DestroyWindow(HWND);
__declspec(dllimport) LRESULT DefWindowProcW(HWND,u32,WPARAM,LPARAM);
__declspec(dllimport) i64 SetWindowLongPtrW(HWND,i32,i64);
__declspec(dllimport) i64 GetWindowLongPtrW(HWND,i32);
__declspec(dllimport) void* CreateSolidBrush(u32);
__declspec(dllimport) void ExitThread(u32);
}
static constexpr u32 ws_child=0x40000000,ws_visible=0x10000000,wm_lbuttondown=0x0201;
static constexpr i32 userdata=-21,width=400,height=300;
static void* module=nullptr;

struct Unknown {virtual i32 queryInterface(uid,void**)=0;virtual u32 addRef()=0;virtual u32 release()=0;};
struct Stream;
struct Handler : Unknown {
 virtual i32 beginEdit(u32)=0;virtual i32 performEdit(u32,double)=0;virtual i32 endEdit(u32)=0;virtual i32 restartComponent(i32)=0;
};

// Every object lives in a fixed pool; a slot is free again once released.
template<class T,int N> struct Pool {
 alignas(16) unsigned char slots[N][sizeof(T)];bool ready=false;
 T* take(){if(!ready){for(int i=0;i<N;++i)new(slots[i]) T;ready=true;}
  for(int i=0;i<N;++i){auto* t=reinterpret_cast<T*>(slots[i]);if(!t->refs){t->reset();t->refs=1;return t;}}return nullptr;}
};

struct BusInfo {i32 mediaType,direction,channelCount;u16 name[128];i32 busType;u32 flags;};
struct RoutingInfo {i32 mediaType,busIndex,channel;};
struct Setup {i32 processMode,symbolicSampleSize,maxSamplesPerBlock;double sampleRate;};
struct Buffers {i32 numChannels;u64 silenceFlags;union {float** f32;double** f64;};};
struct Data {i32 processMode,symbolicSampleSize,numSamples,numInputs,numOutputs;Buffers* inputs;Buffers* outputs;void* rest[5];};
struct Component : Unknown {
 virtual i32 initialize(Unknown*)=0;virtual i32 terminate()=0;virtual i32 getControllerClassId(char*)=0;
 virtual i32 setIoMode(i32)=0;virtual i32 getBusCount(i32,i32)=0;virtual i32 getBusInfo(i32,i32,i32,BusInfo&)=0;
 virtual i32 getRoutingInfo(RoutingInfo&,RoutingInfo&)=0;virtual i32 activateBus(i32,i32,i32,tbool)=0;
 virtual i32 setActive(tbool)=0;virtual i32 setState(Stream*)=0;virtual i32 getState(Stream*)=0;
};
struct Processor : Unknown {
 virtual i32 setBusArrangements(u64*,i32,u64*,i32)=0;virtual i32 getBusArrangement(i32,i32,u64&)=0;
 virtual i32 canProcessSampleSize(i32)=0;virtual u32 getLatencySamples()=0;virtual i32 setupProcessing(Setup&)=0;
 virtual i32 setProcessing(tbool)=0;virtual i32 process(Data&)=0;virtual u32 getTailSamples()=0;
};
struct Effect : Component,Processor {
 u32 refs=0;
 void reset(){}
 i32 queryInterface(uid iid,void** out) override {
  *out=nullptr;
  if(equal(iid,id(component_id))||equal(iid,id(unknown_id))||equal(iid,id(base_id)))*out=static_cast<Component*>(this);
  else if(equal(iid,id(audio_id)))*out=static_cast<Processor*>(this);
  else return nointerface;
  addRef();return ok;
 }
 u32 addRef() override{return ++refs;} u32 release() override{if(refs>0)--refs;return refs;}
 i32 initialize(Unknown*) override{
#ifdef PLUGG_FIXTURE_ENDS_MAIN_THREAD
  ExitThread(0);
#endif
  return ok;
 }
 i32 terminate() override{return ok;}
 i32 getControllerClassId(char* cid) override{memcpy(cid,controller_class,16);return ok;}
 i32 setIoMode(i32) override{return ok;} i32 getBusCount(i32 type,i32) override{return type==0?1:0;}
 i32 getBusInfo(i32 type,i32 dir,i32 index,BusInfo& info) override {
  if(type!=0||index!=0)return no;memset(&info,0,sizeof(info));info.mediaType=type;info.direction=dir;info.channelCount=2;info.flags=1;return ok;
 }
 i32 getRoutingInfo(RoutingInfo&,RoutingInfo&) override{return no;}
 i32 activateBus(i32,i32,i32,tbool) override{return ok;} i32 setActive(tbool) override{return ok;}
 i32 setState(Stream*) override{return ok;} i32 getState(Stream*) override{return ok;}
 i32 setBusArrangements(u64* in,i32 ni,u64* out,i32 no_) override{return ni==1&&no_==1&&in[0]==3&&out[0]==3?ok:no;}
 i32 getBusArrangement(i32,i32 index,u64& arr) override{arr=3;return index==0?ok:no;}
 i32 canProcessSampleSize(i32 size) override{return size==0?ok:no;}u32 getLatencySamples() override{return 0;}
 i32 setupProcessing(Setup& setup) override{return setup.symbolicSampleSize==0?ok:no;}i32 setProcessing(tbool) override{return ok;}
 i32 process(Data& data) override{
  if(data.symbolicSampleSize!=0)return no;
  if(data.numInputs==0||data.numOutputs==0)return ok;
  for(int c=0;c<data.outputs[0].numChannels;++c)for(int s=0;s<data.numSamples;++s)data.outputs[0].f32[c][s]=(c<data.inputs[0].numChannels?data.inputs[0].f32[c][s]*0.5f:0.f);
  data.outputs[0].silenceFlags=0;return ok;
 }u32 getTailSamples() override{return 0;}
};

struct ParameterInfo {u32 id;u16 title[128],shortTitle[128],units[128];i32 stepCount;double defaultNormalizedValue;i32 unitId,flags;};
struct ViewRect {i32 left,top,right,bottom;};
struct Controller;
struct View : Unknown {
 u32 refs=0;Controller* owner=nullptr;HWND window=nullptr;
 void reset(){owner=nullptr;window=nullptr;}
 i32 queryInterface(uid iid,void** out) override{*out=nullptr;if(equal(iid,id(unknown_id))||equal(iid,id(view_id))){*out=this;addRef();return ok;}return nointerface;}
 u32 addRef() override{return ++refs;} u32 release() override;
 virtual i32 isPlatformTypeSupported(const char* type){return same(type,"HWND")?ok:no;}
 virtual i32 attached(void* parent,const char* type);
 virtual i32 removed(){if(window)DestroyWindow(window);window=nullptr;return ok;}
 virtual i32 onWheel(float){return no;}
 virtual i32 onKeyDown(u16,short,short){return no;} virtual i32 onKeyUp(u16,short,short){return no;}
 virtual i32 getSize(ViewRect* size){*size={0,0,width,height};return ok;}
 virtual i32 onSize(ViewRect*){return ok;} virtual i32 onFocus(tbool){return ok;}
 virtual i32 setFrame(Unknown*){return ok;} virtual i32 canResize(){return no;}
 virtual i32 checkSizeConstraint(ViewRect* rect){*rect={0,0,width,height};return ok;}
};
struct Controller : Unknown {
 u32 refs=0;Handler* handler=nullptr;double values[3]={};i32 clicks=0;
 void reset(){handler=nullptr;values[0]=values[1]=values[2]=0;clicks=0;}
 i32 queryInterface(uid iid,void** out) override{
  *out=nullptr;
  if(equal(iid,id(unknown_id))||equal(iid,id(base_id))||equal(iid,id(controller_id))){*out=this;addRef();return ok;}
  return nointerface;
 }
 u32 addRef() override{return ++refs;}
 u32 release() override{if(refs>0)--refs;if(!refs&&handler){handler->release();handler=nullptr;}return refs;}
 virtual i32 initialize(Unknown*){return ok;} virtual i32 terminate(){return ok;}
 virtual i32 setComponentState(Stream*){return ok;} virtual i32 setState(Stream*){return ok;} virtual i32 getState(Stream*){return ok;}
 virtual i32 getParameterCount(){return 3;}
 virtual i32 getParameterInfo(i32 index,ParameterInfo& info){
  static const char* const titles[3]={"Click X","Click Y","Clicks"};
  if(index<0||index>2)return no;memset(&info,0,sizeof(info));info.id=index;wide(info.title,titles[index]);wide(info.shortTitle,titles[index]);
  info.flags=1;return ok;
 }
 virtual i32 getParamStringByValue(u32,double,u16* out){wide(out,"-");return ok;}
 virtual i32 getParamValueByString(u32,u16*,double&){return no;}
 virtual double normalizedParamToPlain(u32,double value){return value;}
 virtual double plainParamToNormalized(u32,double value){return value;}
 virtual double getParamNormalized(u32 param){return param<3?values[param]:0;}
 virtual i32 setParamNormalized(u32 param,double value){if(param>2)return no;values[param]=value;return ok;}
 virtual i32 setComponentHandler(Handler* next){if(next)next->addRef();if(handler)handler->release();handler=next;return ok;}
 virtual View* createView(const char* name);
 void report(u32 param,double value){
  values[param]=value;
  if(handler){handler->beginEdit(param);handler->performEdit(param,value);handler->endEdit(param);}
 }
 void clicked(i32 x,i32 y){report(0,x/4096.0);report(1,y/4096.0);report(2,++clicks/1000.0);}
};
static Pool<Effect,16> effects;static Pool<Controller,16> controllers;static Pool<View,16> views;

u32 View::release(){if(refs>0)--refs;if(!refs){removed();if(owner)owner->release();owner=nullptr;}return refs;}
View* Controller::createView(const char* name){
 if(!name||!same(name,"editor"))return nullptr;
 auto* view=views.take();if(!view)return nullptr;
 view->owner=this;addRef();return view;
}
static LRESULT editor_proc(HWND window,u32 message,WPARAM wparam,LPARAM lparam){
 if(message==wm_lbuttondown){
  if(auto* view=reinterpret_cast<View*>(GetWindowLongPtrW(window,userdata));view&&view->owner)
   view->owner->clicked(static_cast<short>(lparam&0xffff),static_cast<short>((lparam>>16)&0xffff));
  return 0;
 }
 return DefWindowProcW(window,message,wparam,lparam);
}
static const u16 class_name[]={'P','l','u','g','g','T','e','s','t','E','d','i','t','o','r',0};
i32 View::attached(void* parent,const char* type){
 if(!type||!same(type,"HWND")||window)return no;
 static bool registered=false;
 if(!registered){
  WNDCLASSW wc;memset(&wc,0,sizeof(wc));wc.proc=editor_proc;wc.instance=module;wc.name=class_name;
  wc.background=CreateSolidBrush(0x0000c000);
  registered=RegisterClassW(&wc)!=0;
  if(!registered)return no;
 }
 window=CreateWindowExW(0,class_name,class_name,ws_child|ws_visible,0,0,width,height,parent,nullptr,module,nullptr);
 if(!window)return no;
 SetWindowLongPtrW(window,userdata,reinterpret_cast<i64>(this));
 return ok;
}

struct FactoryInfo {char vendor[64],url[256],email[128];i32 flags;};
struct ClassInfo {char cid[16];i32 cardinality;char category[32],name[64];};
struct Factory : Unknown {
 i32 queryInterface(uid iid,void** out) override{*out=nullptr;if(equal(iid,id(unknown_id))||equal(iid,id(factory_id))){*out=this;return ok;}return nointerface;}
 u32 addRef() override{return 1;}u32 release() override{return 1;}
 virtual i32 getFactoryInfo(FactoryInfo* info){memset(info,0,sizeof(*info));text(info->vendor,"Plugg Tests");return ok;}
 virtual i32 countClasses(){return 2;}
 virtual i32 getClassInfo(i32 i,ClassInfo* info){
  if(i<0||i>1)return no;memset(info,0,sizeof(*info));info->cardinality=0x7fffffff;
  if(i==0){memcpy(info->cid,processor_class,16);text(info->category,"Audio Module Class");text(info->name,FIXTURE_NAME);}
  else{memcpy(info->cid,controller_class,16);text(info->category,"Component Controller Class");text(info->name,FIXTURE_NAME " Controller");}
  return ok;
 }
 virtual i32 createInstance(uid cid,uid iid,void** out){
  *out=nullptr;Unknown* made=nullptr;
  if(equal(cid,processor_class)){auto* e=effects.take();made=e?static_cast<Component*>(e):nullptr;}
  else if(equal(cid,controller_class))made=controllers.take();
  else return no;
  if(!made)return no;
  auto result=made->queryInterface(iid,out);made->release();return result;
 }
};
extern "C" __declspec(dllexport) void* GetPluginFactory(){alignas(16) static unsigned char bytes[sizeof(Factory)];static bool ready=false;if(!ready){new(bytes)Factory;ready=true;}return bytes;}
extern "C" __declspec(dllexport) bool InitDll(){return true;}
extern "C" __declspec(dllexport) bool ExitDll(){return true;}
extern "C" int DllMain(void* instance,unsigned,void*){module=instance;return 1;}

extern "C" { int _fltused=0; int _purecall(){return 0;} }
