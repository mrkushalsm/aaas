#include "wire.h"
#include <assert.h>
#include <sys/socket.h>
#include <sys/mman.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
int main(void){int s[2];assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,s));
 aaas_msg m={.magic=AAAS_MAGIC,.version=AAAS_VERSION,.type=AAAS_HELLO};assert(!aaas_send(s[0],&m,0,0));
 aaas_msg out;int fds[AAAS_MAX_FDS];unsigned n;assert(aaas_recv(s[1],&out,fds,&n)==1&&n==0);
 m.type=AAAS_BUFFER;m.generation=1;m.id=1;m.width=64;m.height=64;m.stride=256;m.format=1;
 int fd=memfd_create("invalid-dmabuf",0);assert(fd>=0);assert(!aaas_send(s[0],&m,&fd,1));assert(aaas_recv(s[1],&out,fds,&n)==-1&&errno==EBADFD);close(fd);
 m.type=AAAS_RELEASE;assert(aaas_send(s[0],&m,0,0)==0);assert(aaas_recv(s[1],&out,fds,&n)==1);
 m.version=2;assert(aaas_send(s[0],&m,0,0)==-1&&errno==EINVAL);
 close(s[0]);assert(aaas_recv(s[1],&out,fds,&n)==0);close(s[1]);puts("wire tests passed");}
