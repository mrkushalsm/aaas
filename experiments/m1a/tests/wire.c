#include "wire.h"
#include <assert.h>
#include <sys/socket.h>
#include <sys/mman.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <dirent.h>
#include <string.h>
static int fdcount(void){DIR *d=opendir("/proc/self/fd");assert(d);int n=0;struct dirent *e;while((e=readdir(d)))if(strcmp(e->d_name,".")&&strcmp(e->d_name,".."))n++;closedir(d);return n;}
int main(void){int s[2];assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,s));
 aaas_msg m={.magic=AAAS_MAGIC,.version=AAAS_VERSION,.type=AAAS_HELLO};assert(!aaas_send(s[0],&m,0,0));
 aaas_msg out;int fds[AAAS_MAX_FDS];unsigned n;assert(aaas_recv(s[1],&out,fds,&n)==1&&n==0);
 m.type=AAAS_BUFFER;m.generation=1;m.id=1;m.width=64;m.height=64;m.stride=256;m.format=1;
 int fd=memfd_create("invalid-dmabuf",0);assert(fd>=0);int baseline=fdcount();assert(!aaas_send(s[0],&m,&fd,1));assert(aaas_recv(s[1],&out,fds,&n)==-1&&errno==EBADFD);assert(fdcount()==baseline);close(fd);
 m.type=AAAS_RELEASE;assert(aaas_send(s[0],&m,0,0)==0);assert(aaas_recv(s[1],&out,fds,&n)==1);
 m.version=2;assert(aaas_send(s[0],&m,0,0)==-1&&errno==EINVAL);
 m.version=AAAS_VERSION;assert(aaas_send(s[0],&m,&s[0],1)==-1&&errno==EINVAL);
 m.flags=1;assert(aaas_send(s[0],&m,0,0)==-1&&errno==EINVAL);m.flags=0;
 char short_packet[4]={0};assert(send(s[0],short_packet,sizeof(short_packet),0)==4);assert(aaas_recv(s[1],&out,fds,&n)==-1&&errno==EPROTO&&n==0);
 close(s[0]);assert(aaas_recv(s[1],&out,fds,&n)==0);close(s[1]);puts("wire tests passed");}
