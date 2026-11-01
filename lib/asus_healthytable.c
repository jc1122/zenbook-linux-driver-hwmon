/* SPDX-License-Identifier: GPL-2.0-only */
#define _GNU_SOURCE
#include "asus_healthytable.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <time.h>
#include <signal.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <sys/mman.h>
#include <unistd.h>
#if defined(__i386__) || defined(__x86_64__)
#include <cpuid.h>
#include <sys/syscall.h>
#include <asm/prctl.h>
#endif

#ifndef ASUS_HT_BRIDGE
#define ASUS_HT_BRIDGE "/usr/local/lib/asus-healthytable/0.85.0/api_bridge.py"
#endif
unsigned int asus_ht_abi_version(void) { return 1; }
void asus_ht_free(char *p) { free(p); }

int asus_ht_cpuid(uint32_t leaf, uint32_t subleaf, uint32_t registers[4])
{
    if (!registers) return -EINVAL;
    memset(registers,0,4*sizeof(*registers));
#if defined(__i386__) || defined(__x86_64__)
#if defined(SYS_arch_prctl) && defined(ARCH_GET_CPUID)
    {
        long enabled=syscall(SYS_arch_prctl,ARCH_GET_CPUID,0UL);
        if (enabled==0) return -EOPNOTSUPP;
        if (enabled<0 && errno!=EINVAL && errno!=ENOSYS) return -errno;
    }
#endif
#if defined(__i386__)
    {
        unsigned int signature=0;
        (void)__get_cpuid_max(0,&signature);
        if (!signature) return -EOPNOTSUPP;
    }
#endif
    __cpuid_count(leaf,subleaf,registers[0],registers[1],registers[2],registers[3]);
    return 0;
#else
    (void)leaf;(void)subleaf;
    return -EOPNOTSUPP;
#endif
}

#ifndef ASUS_HT_TIMEOUT_MS
#define ASUS_HT_TIMEOUT_MS 60000
#endif

static long remaining_ms(const struct timespec *deadline)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC,&now)<0) return 0;
    return (long)(deadline->tv_sec-now.tv_sec)*1000+(deadline->tv_nsec-now.tv_nsec)/1000000;
}

/* Keep transport fds above 0..2 so dup2 onto stdin/stdout can never alias or
 * later close them when the caller runs with standard descriptors closed. */
static int high_fd(int fd)
{
    int moved, saved;
    if (fd<0 || fd>2) return fd;
    moved=fcntl(fd,F_DUPFD_CLOEXEC,3);
    saved=errno;close(fd);errno=saved;
    return moved;
}

static int env_ok(const char *value)
{
    return value && *value && strnlen(value,4097)<=4096 && !strchr(value,'\n');
}

/* Fixed, minimal child environment. The interpreter runs isolated (-I ignores
 * PYTHON* variables, user site and the script/current directory), and no
 * caller PATH, LD_* or locale reaches it. An unprivileged, non-setid caller may
 * pass its own desktop-session selectors and system-bus address (the bridge
 * routes privileged names to org.zenbook.Hardware1 there, without interactive
 * authorisation); providers accept only unix: buses. */
static void build_env(char *envp[], size_t slots, char storage[][4200])
{
    static const char *const keep[]={"HOME","XDG_RUNTIME_DIR","XDG_CONFIG_HOME","DBUS_SESSION_BUS_ADDRESS","DBUS_SYSTEM_BUS_ADDRESS"};
    size_t n=0, k;
    envp[n++]="PATH=/usr/sbin:/usr/bin:/sbin:/bin";
    envp[n++]="LANG=C.UTF-8";
    if (geteuid()!=0 && getuid()==geteuid() && getgid()==getegid()) {
        for (k=0;k<sizeof(keep)/sizeof(*keep) && n+1<slots;k++) {
            const char *value=secure_getenv(keep[k]);
            if (!env_ok(value)) continue;
            snprintf(storage[k],4200,"%s=%s",keep[k],value);
            envp[n++]=storage[k];
        }
    }
    envp[n]=NULL;
}

int asus_ht_call(const char *request, char **response)
{
    int output[2]={-1,-1}, input=-1, status=0, error=0, ret, timed_out=0;
    size_t len, used=0, capacity=4096;
    char *buffer=NULL;
    pid_t child;
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attr;
    sigset_t signals;
    struct timespec deadline;
    char *envp[9];
    char storage[5][4200];
    char *const argv[]={"/usr/bin/python3","-I","-B",ASUS_HT_BRIDGE,NULL};
    if (!request || !response) return -EINVAL;
    *response=NULL;
    len=strnlen(request,65537);
    if (len>65536) return -E2BIG;
    /* Anonymous RAM input avoids SIGPIPE, disk files and pipe-size deadlocks. */
    if (pipe2(output,O_CLOEXEC)<0) return -errno;
    output[0]=high_fd(output[0]);
    if (output[0]<0) { error=errno;goto fail; }
    output[1]=high_fd(output[1]);
    if (output[1]<0) { error=errno;goto fail; }
    input=high_fd(memfd_create("asus-ht-request",MFD_CLOEXEC));
    if (input<0) { error=errno; goto fail; }
    while (used<len) {
        ssize_t n=write(input,request+used,len-used);
        if (n<0 && errno==EINTR)continue;
        if (n<=0) {error=errno ? errno : EIO;goto fail;}
        used+=(size_t)n;
    }
    used=0;
    if (lseek(input,0,SEEK_SET)<0) {error=errno;goto fail;}
    build_env(envp,sizeof(envp)/sizeof(*envp),storage);
    ret=posix_spawn_file_actions_init(&actions);
    if (ret) { error=ret;goto fail; }
    ret=posix_spawnattr_init(&attr);
    if (ret) { posix_spawn_file_actions_destroy(&actions);error=ret;goto fail; }
    /* All transport fds are >2 and close-on-exec; only the dup2 copies survive. */
    ret=posix_spawn_file_actions_adddup2(&actions,input,STDIN_FILENO);
    if (!ret) ret=posix_spawn_file_actions_adddup2(&actions,output[1],STDOUT_FILENO);
    if (!ret && fcntl(STDERR_FILENO,F_GETFD)<0)
        ret=posix_spawn_file_actions_addopen(&actions,STDERR_FILENO,"/dev/null",O_WRONLY,0);
#if defined(__GLIBC__) && (__GLIBC__>2 || (__GLIBC__==2 && __GLIBC_MINOR__>=34))
    if (!ret) ret=posix_spawn_file_actions_addclosefrom_np(&actions,3);
#endif
    /* Reset the caller's signal mask and dispositions in the child. */
    sigemptyset(&signals);
    if (!ret) ret=posix_spawnattr_setsigmask(&attr,&signals);
    sigfillset(&signals);sigdelset(&signals,SIGKILL);sigdelset(&signals,SIGSTOP);
    if (!ret) ret=posix_spawnattr_setsigdefault(&attr,&signals);
    if (!ret) ret=posix_spawnattr_setflags(&attr,POSIX_SPAWN_SETSIGMASK|POSIX_SPAWN_SETSIGDEF);
    if (!ret) ret=posix_spawn(&child,argv[0],&actions,&attr,argv,envp);
    posix_spawn_file_actions_destroy(&actions);
    posix_spawnattr_destroy(&attr);
    if (ret) { error=ret;goto fail; }
    close(input);close(output[1]);
    if (clock_gettime(CLOCK_MONOTONIC,&deadline)<0) { error=errno;timed_out=1;kill(child,SIGKILL); }
    deadline.tv_sec+=ASUS_HT_TIMEOUT_MS/1000;
    deadline.tv_nsec+=(long)(ASUS_HT_TIMEOUT_MS%1000)*1000000;
    if (deadline.tv_nsec>=1000000000) { deadline.tv_sec++;deadline.tv_nsec-=1000000000; }
    buffer=malloc(capacity);
    if (!buffer && !error) { error=ENOMEM;kill(child,SIGKILL); }
    while (!error) {
        ssize_t n;
        struct pollfd ready={.fd=output[0],.events=POLLIN};
        long left=remaining_ms(&deadline);
        if (used+2048+1>capacity) {
            char *next;
            if (capacity>=16*1024*1024) {error=E2BIG;kill(child,SIGKILL);break;}
            capacity*=2;next=realloc(buffer,capacity);
            if (!next) {error=ENOMEM;kill(child,SIGKILL);break;}
            buffer=next;
        }
        if (left<=0) {error=ETIMEDOUT;timed_out=1;kill(child,SIGKILL);break;}
        ret=poll(&ready,1,left>INT_MAX ? INT_MAX : (int)left);
        if (ret<0) {if (errno==EINTR)continue;error=errno;kill(child,SIGKILL);break;}
        if (!ret) continue;
        n=read(output[0],buffer+used,capacity-used-1);
        if (n<0) {if (errno==EINTR)continue;error=errno;kill(child,SIGKILL);break;}
        if (!n)break;
        used+=(size_t)n;
    }
    close(output[0]);
    /* Bounded reap: a child that closed stdout but keeps running is killed. */
    for (;;) {
        pid_t r=waitpid(child,&status,timed_out ? 0 : WNOHANG);
        if (r==child) break;
        if (r<0) {if (errno==EINTR)continue;if (!error)error=errno;break;}
        if (remaining_ms(&deadline)<=0) {kill(child,SIGKILL);timed_out=1;if (!error)error=ETIMEDOUT;continue;}
        {
            struct timespec pause={0,10000000};
            nanosleep(&pause,NULL);
        }
    }
    if (error) {free(buffer);return -error;}
    buffer[used]='\0';
    if (!WIFEXITED(status) || !used) {free(buffer);return -EIO;}
    *response=buffer;
    return WEXITSTATUS(status)==0 ? 0 : 1;
fail:
    if (input>=0)close(input);
    if (output[0]>=0)close(output[0]);
    if (output[1]>=0)close(output[1]);
    return -error;
}
