#define _DARWIN_C_SOURCE 1
#define _GNU_SOURCE 1

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <node_api.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#if defined(__APPLE__)
#include <sys/stdio.h>
#elif defined(__linux__)
#include <linux/fs.h>
#include <sys/syscall.h>
#else
#error "Atomic no-replace promotion is unsupported on this platform."
#endif

static napi_value throw_failure(napi_env env, const char *code, const char *message) {
  napi_throw_error(env, code, message);
  return NULL;
}

static napi_value throw_native_failure(napi_env env, const char *fallback, int native_error) {
  if (native_error == EEXIST || native_error == ENOTEMPTY) {
    return throw_failure(env, "EEXIST", "Atomic promotion destination is occupied.");
  }
  if (native_error == ENOSYS || native_error == ENOTSUP || native_error == EOPNOTSUPP || native_error == EINVAL) {
    return throw_failure(env, "ENOTSUP", "Atomic no-replace promotion is unsupported by this filesystem.");
  }
  return throw_failure(env, "EIO", fallback);
}

static int valid_name(const char *value) {
  return value != NULL && value[0] != '\0' && strcmp(value, ".") != 0 && strcmp(value, "..") != 0 &&
         strchr(value, '/') == NULL && strchr(value, '\\') == NULL;
}

static int parse_u64(const char *value, uint64_t *parsed) {
  char *end = NULL;
  unsigned long long number;
  if (value == NULL || value[0] == '\0' || value[0] == '-' || value[0] == '+') return 0;
  errno = 0;
  number = strtoull(value, &end, 10);
  if (errno != 0 || end == value || *end != '\0') return 0;
  *parsed = (uint64_t)number;
  return 1;
}

static int atomic_rename_no_replace(int parent_fd, const char *source, const char *destination) {
#if defined(__APPLE__)
  return renameatx_np(parent_fd, source, parent_fd, destination, RENAME_EXCL);
#elif defined(__linux__)
  return (int)syscall(SYS_renameat2, parent_fd, source, parent_fd, destination, RENAME_NOREPLACE);
#endif
}

static int read_string(napi_env env, napi_value value, char *buffer, size_t capacity) {
  napi_valuetype type;
  size_t required = 0;
  size_t copied = 0;
  if (napi_typeof(env, value, &type) != napi_ok || type != napi_string ||
      napi_get_value_string_utf8(env, value, NULL, 0, &required) != napi_ok ||
      required == 0 || required >= capacity ||
      napi_get_value_string_utf8(env, value, buffer, capacity, &copied) != napi_ok ||
      copied != required || buffer[required] != '\0' || memchr(buffer, '\0', required) != NULL) return 0;
  return 1;
}

static napi_value promote_absent(napi_env env, napi_callback_info info) {
  napi_value arguments[7];
  size_t argument_count = 7;
  char parent[PATH_MAX];
  char canonical_parent[PATH_MAX];
  char source[NAME_MAX + 1];
  char destination[NAME_MAX + 1];
  char expected_dev_text[32];
  char expected_ino_text[32];
  char expected_parent_dev_text[32];
  char expected_parent_ino_text[32];
  uint64_t expected_dev;
  uint64_t expected_ino;
  uint64_t expected_parent_dev;
  uint64_t expected_parent_ino;
  struct stat parent_stat;
  struct stat source_stat;
  struct stat destination_stat;
  struct stat source_after;
  int parent_fd = -1;
  int source_fd = -1;

  if (napi_get_cb_info(env, info, &argument_count, arguments, NULL, NULL) != napi_ok || argument_count != 7 ||
      !read_string(env, arguments[0], parent, sizeof(parent)) ||
      !read_string(env, arguments[1], source, sizeof(source)) ||
      !read_string(env, arguments[2], destination, sizeof(destination)) ||
      !read_string(env, arguments[3], expected_dev_text, sizeof(expected_dev_text)) ||
      !read_string(env, arguments[4], expected_ino_text, sizeof(expected_ino_text)) ||
      !read_string(env, arguments[5], expected_parent_dev_text, sizeof(expected_parent_dev_text)) ||
      !read_string(env, arguments[6], expected_parent_ino_text, sizeof(expected_parent_ino_text)) ||
      parent[0] != '/' || !valid_name(source) || !valid_name(destination) || strcmp(source, destination) == 0 ||
      !parse_u64(expected_dev_text, &expected_dev) || !parse_u64(expected_ino_text, &expected_ino) ||
      !parse_u64(expected_parent_dev_text, &expected_parent_dev) ||
      !parse_u64(expected_parent_ino_text, &expected_parent_ino)) {
    return throw_failure(env, "EINVAL", "Atomic promotion arguments are invalid.");
  }
  if (realpath(parent, canonical_parent) == NULL) {
    const int native_error = errno;
    return throw_native_failure(env, "Atomic promotion parent is unavailable.", native_error);
  }
  if (strcmp(parent, canonical_parent) != 0) {
    return throw_failure(env, "EINVAL", "Atomic promotion parent is aliased.");
  }

  parent_fd = open(parent, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
  if (parent_fd < 0) {
    const int native_error = errno;
    return throw_native_failure(env, "Atomic promotion parent could not be pinned.", native_error);
  }
  if (fstat(parent_fd, &parent_stat) != 0) {
    const int native_error = errno;
    close(parent_fd);
    return throw_native_failure(env, "Atomic promotion parent identity is unavailable.", native_error);
  }
  if (!S_ISDIR(parent_stat.st_mode) || (uint64_t)parent_stat.st_dev != expected_parent_dev ||
      (uint64_t)parent_stat.st_ino != expected_parent_ino) {
    close(parent_fd);
    return throw_failure(env, "ESTALE", "Atomic promotion parent identity changed.");
  }
  source_fd = openat(parent_fd, source, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
  if (source_fd < 0) {
    const int native_error = errno;
    close(parent_fd);
    return throw_native_failure(env, "Atomic promotion source could not be pinned.", native_error);
  }
  if (fstat(source_fd, &source_stat) != 0) {
    const int native_error = errno;
    close(source_fd);
    close(parent_fd);
    return throw_native_failure(env, "Atomic promotion source identity is unavailable.", native_error);
  }
  if (!S_ISDIR(source_stat.st_mode) || (uint64_t)source_stat.st_dev != expected_dev ||
      (uint64_t)source_stat.st_ino != expected_ino) {
    close(source_fd);
    close(parent_fd);
    return throw_failure(env, "ESTALE", "Atomic promotion source identity changed.");
  }

  if (atomic_rename_no_replace(parent_fd, source, destination) != 0) {
    const int native_error = errno;
    close(source_fd);
    close(parent_fd);
    return throw_native_failure(env, "Atomic no-replace promotion failed.", native_error);
  }
  if (fstatat(parent_fd, destination, &destination_stat, AT_SYMLINK_NOFOLLOW) != 0) {
    const int native_error = errno;
    close(source_fd);
    close(parent_fd);
    return throw_native_failure(env, "Atomic promotion destination postcondition failed.", native_error);
  }
  if (!S_ISDIR(destination_stat.st_mode) || destination_stat.st_dev != source_stat.st_dev ||
      destination_stat.st_ino != source_stat.st_ino) {
    close(source_fd);
    close(parent_fd);
    return throw_failure(env, "ESTALE", "Atomic promotion destination identity changed.");
  }
  errno = 0;
  if (fstatat(parent_fd, source, &source_after, AT_SYMLINK_NOFOLLOW) == 0) {
    close(source_fd);
    close(parent_fd);
    return throw_failure(env, "ESTALE", "Atomic promotion source still exists after settlement.");
  }
  {
    const int native_error = errno;
    if (native_error != ENOENT) {
      close(source_fd);
      close(parent_fd);
      return throw_native_failure(env, "Atomic promotion source postcondition failed.", native_error);
    }
  }
  if (fsync(parent_fd) != 0) {
    const int native_error = errno;
    close(source_fd);
    close(parent_fd);
    return throw_native_failure(env, "Atomic promotion parent durability is unavailable.", native_error);
  }
  close(source_fd);
  close(parent_fd);
  napi_value result;
  if (napi_get_undefined(env, &result) != napi_ok) return NULL;
  return result;
}

NAPI_MODULE_INIT() {
  napi_value function;
  if (napi_create_function(env, "promoteAbsent", NAPI_AUTO_LENGTH, promote_absent, NULL, &function) != napi_ok ||
      napi_set_named_property(env, exports, "promoteAbsent", function) != napi_ok) {
    return NULL;
  }
  return exports;
}
