const { withAndroidManifest } = require('expo/config-plugins');

module.exports = function withTermux(config) {
  return withAndroidManifest(config, (config) => {
    const manifest = config.modResults.manifest;
    const permissions = manifest['uses-permission'] || [];
    const permissionName = 'com.termux.permission.RUN_COMMAND';
    if (!permissions.some((item) => item?.$?.['android:name'] === permissionName)) {
      permissions.push({ $: { 'android:name': permissionName } });
    }
    manifest['uses-permission'] = permissions;

    const queries = manifest.queries || [];
    const hasTermuxQuery = queries.some((entry) =>
      (entry.package || []).some((item) => item?.$?.['android:name'] === 'com.termux'),
    );
    if (!hasTermuxQuery) {
      queries.push({ package: [{ $: { 'android:name': 'com.termux' } }] });
    }
    manifest.queries = queries;
    return config;
  });
};
