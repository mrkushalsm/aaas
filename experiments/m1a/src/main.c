#include "wire.h"
#include "xdg-shell-client-protocol.h"
#include "linux-dmabuf-client-protocol.h"
#include "presentation-time-client-protocol.h"
#include <wayland-client.h>
#include <gbm.h>
#include <drm_fourcc.h>
#include <sys/socket.h>
#include <sys/poll.h>
#include <sys/wait.h>
#include <sys/resource.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#define NBUF 3
static volatile sig_atomic_t running=1;
static void stop(int x){(void)x;running=0;}
static aaas_msg msg(uint32_t type,uint32_t gen,uint32_t id){return (aaas_msg){.magic=AAAS_MAGIC,.version=AAAS_VERSION,.type=type,.generation=gen,.id=id};}
static void logevent(const char *role,const char *event,unsigned gen,unsigned id){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);fprintf(stderr,"{\"t_ns\":%lld,\"role\":\"%s\",\"event\":\"%s\",\"generation\":%u,\"id\":%u}\n",(long long)t.tv_sec*1000000000LL+t.tv_nsec,role,event,gen,id);}
typedef struct {struct gbm_bo *bo;uint32_t id,gen;int busy;} pbuf;
static int producer(int sock,const char *node){int devfd=open(node,O_RDWR|O_CLOEXEC);if(devfd<0){perror("render node");return 2;}struct gbm_device *dev=gbm_create_device(devfd);if(!dev){perror("gbm device");close(devfd);return 2;}
 pbuf b[NBUF]={0};uint32_t gen=0,w=0,h=0,nextid=1,frame=0;struct timespec next={0};
 while(running){struct pollfd p={.fd=sock,.events=POLLIN};int pr=poll(&p,1,33);if(pr<0){if(errno==EINTR)continue;break;}if(p.revents&(POLLHUP|POLLERR)){logevent("producer","presenter_disconnect",gen,0);break;}
 if(p.revents&POLLIN){aaas_msg m;int fds[AAAS_MAX_FDS];unsigned n;int r=aaas_recv(sock,&m,fds,&n);if(r<=0){logevent("producer","presenter_disconnect",gen,0);break;}if(m.type==AAAS_RESIZE&&m.generation>gen&&m.width&&m.height&&m.width<=AAAS_MAX_DIM&&m.height<=AAAS_MAX_DIM){for(int i=0;i<NBUF;i++)if(b[i].bo&&!b[i].busy){gbm_bo_destroy(b[i].bo);b[i]=(pbuf){0};}gen=m.generation;w=m.width;h=m.height;logevent("producer","resize",gen,0);}else if(m.type==AAAS_RELEASE){for(int i=0;i<NBUF;i++)if(b[i].id==m.id&&b[i].gen==m.generation&&b[i].busy){b[i].busy=0;logevent("producer","release",m.generation,m.id);}}else if(m.type==AAAS_CLOSE)break;else logevent("producer","stale_or_invalid_order",m.generation,m.id);}
 if(!gen)continue;
 int i;for(i=0;i<NBUF;i++)if(!b[i].busy)break;
 if(i==NBUF)continue;
 if(b[i].bo&&b[i].gen!=gen){gbm_bo_destroy(b[i].bo);b[i]=(pbuf){0};}
 if(!b[i].bo){b[i].bo=gbm_bo_create(dev,w,h,GBM_FORMAT_XRGB8888,GBM_BO_USE_LINEAR|GBM_BO_USE_RENDERING);if(!b[i].bo){logevent("producer","gbm_alloc_failed",gen,0);break;}b[i].id=nextid++;b[i].gen=gen;}
 uint32_t stride=0;void *mapdata=0;void *px=gbm_bo_map(b[i].bo,0,0,w,h,GBM_BO_TRANSFER_WRITE,&stride,&mapdata);if(!px){logevent("producer","gbm_map_failed",gen,b[i].id);break;}
 for(uint32_t y=0;y<h;y++){uint32_t *row=(uint32_t*)((char*)px+y*stride);for(uint32_t x=0;x<w;x++)row[x]=((x+frame*3)&255)<<16|((y+frame*2)&255)<<8|((frame*7)&255);}gbm_bo_unmap(b[i].bo,mapdata);
 int fd=gbm_bo_get_fd(b[i].bo);if(fd<0){logevent("producer","export_failed",gen,b[i].id);break;}
 aaas_msg m=msg(AAAS_BUFFER,gen,b[i].id);m.width=w;m.height=h;m.format=DRM_FORMAT_XRGB8888;m.modifier=gbm_bo_get_modifier(b[i].bo);m.stride=gbm_bo_get_stride(b[i].bo);m.offset=gbm_bo_get_offset(b[i].bo,0);int r=aaas_send(sock,&m,&fd,1);close(fd);if(r){perror("send buffer");break;}b[i].busy=1;frame++;logevent("producer","frame_sent_cpu_write",gen,b[i].id);
 struct timespec delay={.tv_nsec=16000000};nanosleep(&delay,0);(void)next;
 }
 for(int i=0;i<NBUF;i++)if(b[i].bo)gbm_bo_destroy(b[i].bo);
 gbm_device_destroy(dev);close(devfd);return 0;}
typedef struct app app;
typedef struct {struct wl_buffer *wl;app *a;uint32_t id,gen;int active;} slot;
struct app {struct wl_display *d;struct wl_registry *reg;struct wl_compositor *comp;struct xdg_wm_base *wm;struct zwp_linux_dmabuf_v1 *dma;struct wp_presentation *pres;struct wl_surface *surface;struct xdg_surface *xs;struct xdg_toplevel *top;int sock,configured,closed;uint32_t gen,w,h;uint64_t formats[512];unsigned nformats;slot slots[32];uint64_t imported,submitted,released,rejected,presented,discarded;};
static void dmformat(void *data,struct zwp_linux_dmabuf_v1 *obj,uint32_t f){(void)data;(void)obj;(void)f;}
static void dmmod(void *data,struct zwp_linux_dmabuf_v1 *obj,uint32_t f,uint32_t hi,uint32_t lo){(void)obj;app *a=data;uint64_t mod=((uint64_t)hi<<32)|lo;if(f==DRM_FORMAT_XRGB8888&&a->nformats<512)a->formats[a->nformats++]=mod;}
static const struct zwp_linux_dmabuf_v1_listener dml={dmformat,dmmod};
static void globals(void *data,struct wl_registry *r,uint32_t name,const char *iface,uint32_t ver){app *a=data;if(!strcmp(iface,"wl_compositor"))a->comp=wl_registry_bind(r,name,&wl_compositor_interface,ver<4?ver:4);else if(!strcmp(iface,"xdg_wm_base"))a->wm=wl_registry_bind(r,name,&xdg_wm_base_interface,ver<3?ver:3);else if(!strcmp(iface,"wp_presentation"))a->pres=wl_registry_bind(r,name,&wp_presentation_interface,1);else if(!strcmp(iface,"zwp_linux_dmabuf_v1")&&ver>=3)a->dma=wl_registry_bind(r,name,&zwp_linux_dmabuf_v1_interface,3);}
static void globalgone(void *data,struct wl_registry *r,uint32_t n){(void)data;(void)r;(void)n;}
static const struct wl_registry_listener regl={globals,globalgone};
static void ping(void *data,struct xdg_wm_base *wm,uint32_t serial){(void)data;xdg_wm_base_pong(wm,serial);}
static const struct xdg_wm_base_listener wml={ping};
static void configure(void *data,struct xdg_surface *xs,uint32_t serial){app *a=data;xdg_surface_ack_configure(xs,serial);a->configured=1;uint32_t w=a->w?a->w:640,h=a->h?a->h:480;if(w>1920)w=1920;if(h>1080)h=1080;a->gen++;aaas_msg m=msg(AAAS_RESIZE,a->gen,0);m.width=w;m.height=h;if(aaas_send(a->sock,&m,0,0))a->closed=1;logevent("presenter","configure",a->gen,0);}
static const struct xdg_surface_listener xsl={configure};
static void topconf(void *data,struct xdg_toplevel *t,int32_t w,int32_t h,struct wl_array *states){(void)t;(void)states;app *a=data;if(w>0)a->w=(uint32_t)w;if(h>0)a->h=(uint32_t)h;}
static void topclose(void *data,struct xdg_toplevel *t){(void)t;app *a=data;a->closed=1;logevent("presenter","close",a->gen,0);}
static const struct xdg_toplevel_listener topl={.configure=topconf,.close=topclose};
static void released(void *data,struct wl_buffer *buf){slot *s=data;app *a=s->a;aaas_msg m=msg(AAAS_RELEASE,s->gen,s->id);if(aaas_send(a->sock,&m,0,0))a->closed=1;logevent("presenter","wl_buffer_release",s->gen,s->id);a->released++;wl_buffer_destroy(buf);s->active=0;}
static const struct wl_buffer_listener bufl={released};
static int supported(app *a,uint64_t mod){for(unsigned i=0;i<a->nformats;i++)if(a->formats[i]==mod)return 1;return 0;}
static void clockid(void *data,struct wp_presentation *p,uint32_t id){(void)data;(void)p;fprintf(stderr,"{\"event\":\"presentation_clock\",\"clock_id\":%u}\n",id);}
static const struct wp_presentation_listener presl={clockid};
static void syncout(void *data,struct wp_presentation_feedback *f,struct wl_output *o){(void)data;(void)f;(void)o;}
static void presented(void *data,struct wp_presentation_feedback *f,uint32_t sh,uint32_t sl,uint32_t ns,uint32_t refresh,uint32_t qh,uint32_t ql,uint32_t flags){(void)sh;(void)sl;(void)ns;(void)refresh;(void)qh;(void)ql;app *a=data;a->presented++;fprintf(stderr,"{\"event\":\"presented\",\"flags\":%u}\n",flags);wp_presentation_feedback_destroy(f);}
static void discarded(void *data,struct wp_presentation_feedback *f){app *a=data;a->discarded++;logevent("presenter","presentation_discarded",a->gen,0);wp_presentation_feedback_destroy(f);}
static const struct wp_presentation_feedback_listener pfl={syncout,presented,discarded};
static void incoming(app *a){aaas_msg m;int fds[AAAS_MAX_FDS];unsigned n;int r=aaas_recv(a->sock,&m,fds,&n);if(r<=0){a->closed=1;logevent("presenter",r<0?"invalid_message":"producer_disconnect",a->gen,0);return;}if(m.type!=AAAS_BUFFER||!a->configured||m.generation!=a->gen||m.width!=(a->w?a->w:640)||m.height!=(a->h?a->h:480)||m.format!=DRM_FORMAT_XRGB8888||m.stride<m.width*4||m.stride>65536||m.offset>65536||!supported(a,m.modifier)){for(unsigned i=0;i<n;i++)close(fds[i]);a->rejected++;logevent("presenter","rejected_stale_or_format",m.generation,m.id);return;}
 slot *s=0;for(int i=0;i<32;i++)if(!a->slots[i].active){s=&a->slots[i];break;}if(!s){close(fds[0]);a->rejected++;return;}
 struct zwp_linux_buffer_params_v1 *p=zwp_linux_dmabuf_v1_create_params(a->dma);zwp_linux_buffer_params_v1_add(p,fds[0],0,m.offset,m.stride,(uint32_t)(m.modifier>>32),(uint32_t)m.modifier);close(fds[0]);
 struct wl_buffer *buf=zwp_linux_buffer_params_v1_create_immed(p,m.width,m.height,m.format,0);zwp_linux_buffer_params_v1_destroy(p);if(!buf){a->rejected++;logevent("presenter","import_failed",m.generation,m.id);return;}
 s->wl=buf;s->a=a;s->id=m.id;s->gen=m.generation;s->active=1;wl_buffer_add_listener(buf,&bufl,s);a->imported++;wl_surface_attach(a->surface,buf,0,0);wl_surface_damage_buffer(a->surface,0,0,m.width,m.height);if(a->pres){struct wp_presentation_feedback *fb=wp_presentation_feedback(a->pres,a->surface);wp_presentation_feedback_add_listener(fb,&pfl,a);}wl_surface_commit(a->surface);a->submitted++;logevent("presenter","dmabuf_import_submit",m.generation,m.id);}
static int presenter(int sock){app a={.sock=sock,.w=640,.h=480};a.d=wl_display_connect(0);if(!a.d){perror("Wayland connection");return 2;}a.reg=wl_display_get_registry(a.d);wl_registry_add_listener(a.reg,&regl,&a);if(wl_display_roundtrip(a.d)<0||!a.comp||!a.wm||!a.dma){fprintf(stderr,"required Wayland globals absent\n");return 2;}zwp_linux_dmabuf_v1_add_listener(a.dma,&dml,&a);if(a.pres)wp_presentation_add_listener(a.pres,&presl,&a);xdg_wm_base_add_listener(a.wm,&wml,&a);wl_display_roundtrip(a.d);fprintf(stderr,"{\"event\":\"capabilities\",\"xr24_modifiers\":%u,\"explicit_sync\":false}\n",a.nformats);if(!a.nformats)return 2;
 a.surface=wl_compositor_create_surface(a.comp);a.xs=xdg_wm_base_get_xdg_surface(a.wm,a.surface);xdg_surface_add_listener(a.xs,&xsl,&a);a.top=xdg_surface_get_toplevel(a.xs);xdg_toplevel_add_listener(a.top,&topl,&a);xdg_toplevel_set_title(a.top,"AaaS M1A DMA-BUF prototype");wl_surface_commit(a.surface);
 while(running&&!a.closed){while(wl_display_prepare_read(a.d)!=0){if(wl_display_dispatch_pending(a.d)<0){logevent("presenter","compositor_disconnect",a.gen,0);a.closed=1;break;}}if(a.closed)break;if(wl_display_flush(a.d)<0&&errno!=EAGAIN){wl_display_cancel_read(a.d);logevent("presenter","compositor_disconnect",a.gen,0);break;}struct pollfd p[2]={{.fd=wl_display_get_fd(a.d),.events=POLLIN},{.fd=sock,.events=POLLIN}};int r=poll(p,2,200);if(r<0){wl_display_cancel_read(a.d);if(errno==EINTR)continue;break;}if(p[0].revents&POLLIN){if(wl_display_read_events(a.d)<0){logevent("presenter","compositor_disconnect",a.gen,0);break;}wl_display_dispatch_pending(a.d);}else wl_display_cancel_read(a.d);if(p[0].revents&(POLLHUP|POLLERR)){logevent("presenter","compositor_disconnect",a.gen,0);break;}if(p[1].revents&POLLIN)incoming(&a);if(p[1].revents&(POLLHUP|POLLERR)){logevent("presenter","producer_disconnect",a.gen,0);break;}}
 aaas_msg closemsg=msg(AAAS_CLOSE,a.gen,0);aaas_send(sock,&closemsg,0,0);struct rusage usage;getrusage(RUSAGE_SELF,&usage);fprintf(stderr,"{\"event\":\"summary\",\"imports\":%llu,\"submissions\":%llu,\"releases\":%llu,\"rejected\":%llu,\"presented\":%llu,\"discarded\":%llu,\"maxrss_kib\":%ld,\"user_us\":%ld,\"system_us\":%ld,\"host_cpu_copies\":0,\"gpu_conversions\":0}\n",(unsigned long long)a.imported,(unsigned long long)a.submitted,(unsigned long long)a.released,(unsigned long long)a.rejected,(unsigned long long)a.presented,(unsigned long long)a.discarded,usage.ru_maxrss,usage.ru_utime.tv_sec*1000000L+usage.ru_utime.tv_usec,usage.ru_stime.tv_sec*1000000L+usage.ru_stime.tv_usec);
 for(int i=0;i<32;i++)if(a.slots[i].active)wl_buffer_destroy(a.slots[i].wl);
 xdg_toplevel_destroy(a.top);xdg_surface_destroy(a.xs);wl_surface_destroy(a.surface);zwp_linux_dmabuf_v1_destroy(a.dma);if(a.pres)wp_presentation_destroy(a.pres);xdg_wm_base_destroy(a.wm);wl_compositor_destroy(a.comp);wl_registry_destroy(a.reg);wl_display_disconnect(a.d);return a.imported&&a.released?0:1;}
int main(int argc,char **argv){signal(SIGINT,stop);signal(SIGTERM,stop);int s[2];if(socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,s)){perror("socketpair");return 2;}pid_t child=fork();if(child<0)return 2;if(!child){close(s[0]);int r=producer(s[1],argc>1?argv[1]:"/dev/dri/renderD129");close(s[1]);_exit(r);}close(s[1]);int r=presenter(s[0]);close(s[0]);kill(child,SIGTERM);waitpid(child,0,0);return r;}
