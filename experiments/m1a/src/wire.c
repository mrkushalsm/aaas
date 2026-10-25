#include "wire.h"
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>
static int valid(const aaas_msg *m,unsigned n){
 if(m->magic!=AAAS_MAGIC||m->version!=AAAS_VERSION||m->reserved||m->type<AAAS_HELLO||m->type>AAAS_CLOSE)return 0;
 if(m->type==AAAS_BUFFER) return n==1&&m->generation&&m->id&&m->width&&m->height&&m->width<=AAAS_MAX_DIM&&m->height<=AAAS_MAX_DIM&&m->stride&&m->format;
 return n==0;
}
int aaas_send(int s,const aaas_msg *m,const int *fds,unsigned n){
 if(n>AAAS_MAX_FDS||!valid(m,n)){errno=EINVAL;return -1;}
 struct iovec iov={.iov_base=(void*)m,.iov_len=sizeof(*m)};
 char ctrl[CMSG_SPACE(sizeof(int)*AAAS_MAX_FDS)]={0};
 struct msghdr h={.msg_iov=&iov,.msg_iovlen=1};
 if(n){h.msg_control=ctrl;h.msg_controllen=CMSG_SPACE(sizeof(int)*n);struct cmsghdr *c=CMSG_FIRSTHDR(&h);c->cmsg_level=SOL_SOCKET;c->cmsg_type=SCM_RIGHTS;c->cmsg_len=CMSG_LEN(sizeof(int)*n);memcpy(CMSG_DATA(c),fds,sizeof(int)*n);}
 ssize_t r=sendmsg(s,&h,MSG_NOSIGNAL);return r==(ssize_t)sizeof(*m)?0:-1;
}
int aaas_recv(int s,aaas_msg *m,int *fds,unsigned *n){
 *n=0;struct iovec iov={.iov_base=m,.iov_len=sizeof(*m)};
 char ctrl[CMSG_SPACE(sizeof(int)*AAAS_MAX_FDS)]={0};
 struct msghdr h={.msg_iov=&iov,.msg_iovlen=1,.msg_control=ctrl,.msg_controllen=sizeof(ctrl)};
 ssize_t r=recvmsg(s,&h,MSG_CMSG_CLOEXEC);if(r<=0)return (int)r;
 for(struct cmsghdr *c=CMSG_FIRSTHDR(&h);c;c=CMSG_NXTHDR(&h,c))if(c->cmsg_level==SOL_SOCKET&&c->cmsg_type==SCM_RIGHTS){unsigned k=(c->cmsg_len-CMSG_LEN(0))/sizeof(int);int *p=(int*)CMSG_DATA(c);for(unsigned i=0;i<k;i++){if(*n<AAAS_MAX_FDS)fds[(*n)++]=p[i];else close(p[i]);}}
 if(r!=(ssize_t)sizeof(*m)||(h.msg_flags&(MSG_TRUNC|MSG_CTRUNC))||!valid(m,*n)){for(unsigned i=0;i<*n;i++)close(fds[i]);*n=0;errno=EPROTO;return -1;}
 if(m->type==AAAS_BUFFER){struct stat st;char link[128],path[64];snprintf(path,sizeof(path),"/proc/self/fd/%d",fds[0]);ssize_t len=readlink(path,link,sizeof(link)-1);if(len>=0)link[len]=0;if(fstat(fds[0],&st)||len<0||!(!strncmp(link,"/dmabuf:",8)||!strncmp(link,"anon_inode:[dmabuf]",19))){close(fds[0]);*n=0;errno=EBADFD;return -1;}}
 return 1;
}
