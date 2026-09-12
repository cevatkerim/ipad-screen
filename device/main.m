#import <UIKit/UIKit.h>
#import <AVFoundation/AVFoundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

static NSString *const StatusPath = @"/var/mobile/Library/Caches/ipad-screen-status.json";
static NSString *const TokenPath = @"/var/mobile/Library/Preferences/ipad-screen-token";
static BOOL ReadAll(int fd, void *buf, size_t len) {
    size_t offset = 0;
    while (offset < len) { ssize_t n = read(fd, (char *)buf + offset, len - offset); if (n <= 0) return NO; offset += n; }
    return YES;
}
static BOOL WriteAll(int fd, const void *buf, size_t len) {
    size_t offset = 0;
    while (offset < len) { ssize_t n = write(fd, (const char *)buf + offset, len - offset); if (n <= 0) return NO; offset += n; }
    return YES;
}

@interface ScreenController : UIViewController {
    CMVideoFormatDescriptionRef _format;
    NSData *_sps, *_pps;
    BOOL _needsIDR;
    BOOL _hardware;
    uint32_t _received, _queued, _errors, _dropped;
    NSInteger _renderStatus;
    uint32_t _width, _height;
    OSStatus _lastError;
    NSString *_lastStage;
    NSTimeInterval _started, _lastStatus;
}
@property(nonatomic) AVSampleBufferDisplayLayer *video;
@property(nonatomic) UILabel *label;
@property(nonatomic) BOOL showStats;
@end

@implementation ScreenController
- (BOOL)prefersStatusBarHidden { return YES; }
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskLandscape; }
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.blackColor;
    self.video = [AVSampleBufferDisplayLayer layer];
    self.video.videoGravity = AVLayerVideoGravityResizeAspect;
    [self.view.layer addSublayer:self.video];
    self.label = [[UILabel alloc] init];
    self.label.textColor = UIColor.whiteColor;
    self.label.backgroundColor = [UIColor colorWithWhite:0.08 alpha:0.85];
    self.label.font = [UIFont monospacedSystemFontOfSize:16 weight:UIFontWeightMedium];
    self.label.numberOfLines = 0;
    self.label.text = @"iPad Screen\nConnect your computer by USB";
    [self.view addSubview:self.label];
    [self.view addGestureRecognizer:[[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(toggleStats)]];
    UIApplication.sharedApplication.idleTimerDisabled = YES;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INTERACTIVE, 0), ^{ [self listen]; });
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    self.video.frame = self.view.bounds;
    self.label.frame = CGRectMake(20, 20, MIN(650, self.view.bounds.size.width - 40), 90);
}
- (void)toggleStats { self.showStats = !self.showStats; self.label.hidden = !self.showStats && _queued > 0; }
- (void)status:(NSString *)state force:(BOOL)force {
    NSTimeInterval now = NSDate.date.timeIntervalSince1970;
    if (!force && now - _lastStatus < 1) return;
    _lastStatus = now;
    NSDictionary *report = @{ @"state":state, @"received":@(_received),
        @"queued":@(_queued), @"dropped":@(_dropped), @"rendering_status":@(_renderStatus), @"errors":@(_errors), @"width":@(_width), @"height":@(_height),
        @"hardware_h264_supported":@(_hardware), @"last_osstatus":@(_lastError), @"last_stage":_lastStage ?: @"none", @"elapsed_seconds":@(MAX(0, now - _started)), @"timestamp":@(now) };
    [[NSJSONSerialization dataWithJSONObject:report options:0 error:nil] writeToFile:StatusPath atomically:YES];
}
- (void)resetFormat {
    if (_format) { CFRelease(_format); _format = NULL; }
    _needsIDR = YES;
}
- (BOOL)makeFormat {
    [self resetFormat];
    dispatch_sync(dispatch_get_main_queue(), ^{ [self.video flushAndRemoveImage]; });
    const uint8_t *sets[] = {_sps.bytes, _pps.bytes}; size_t sizes[] = {_sps.length, _pps.length};
    OSStatus result = CMVideoFormatDescriptionCreateFromH264ParameterSets(kCFAllocatorDefault, 2, sets, sizes, 4, &_format);
    if (result) { _lastError = result; return NO; }
    CMVideoDimensions dims = CMVideoFormatDescriptionGetDimensions(_format);
    if (dims.width <= 0 || dims.height <= 0 || dims.width > 4096 || dims.height > 4096) { [self resetFormat]; return NO; }
    _width = dims.width; _height = dims.height;
    // iOS headers do not expose macOS's per-session hardware-selection key.
    _hardware = VTIsHardwareDecodeSupported(kCMVideoCodecType_H264);
    return YES;
}
- (void)consume:(NSData *)accessUnit {
    _received++;
    NSMutableData *picture = [NSMutableData data];
    BOOL changed = NO, idr = NO;
    const uint8_t *bytes = accessUnit.bytes;
    size_t offset = 0;
    while (offset + 4 <= accessUnit.length) {
        uint32_t length; memcpy(&length, bytes + offset, 4); length = ntohl(length); offset += 4;
        if (!length || length > accessUnit.length - offset) { _errors++; return; }
        uint8_t type = bytes[offset] & 31;
        if (type == 7 || type == 8) {
            NSData *set = [NSData dataWithBytes:bytes + offset length:length];
            if (type == 7 && ![set isEqual:_sps]) { _sps = set; changed = YES; }
            if (type == 8 && ![set isEqual:_pps]) { _pps = set; changed = YES; }
        } else if (type == 1 || type == 5 || type == 6) {
            [picture appendBytes:bytes + offset - 4 length:length + 4];
            if (type == 5) idr = YES;
        }
        offset += length;
    }
    if (offset != accessUnit.length) { _errors++; return; }
    if ((!_format || changed) && _sps && _pps && ![self makeFormat]) { _errors++; return; }
    if (!_format || !picture.length || (_needsIDR && !idr)) { _dropped++; return; }
    _needsIDR = NO;
    CMBlockBufferRef block = NULL; CMSampleBufferRef sample = NULL;
    OSStatus result = CMBlockBufferCreateWithMemoryBlock(kCFAllocatorDefault, NULL, picture.length,
        kCFAllocatorDefault, NULL, 0, picture.length, 0, &block);
    _lastStage = @"block-create";
    if (!result) { _lastStage = @"block-copy"; result = CMBlockBufferReplaceDataBytes(picture.bytes, block, 0, picture.length); }
    size_t size = picture.length;
    if (!result) { _lastStage = @"sample-create"; result = CMSampleBufferCreateReady(kCFAllocatorDefault, block, _format, 1, 0, NULL, 1, &size, &sample); }
    if (!result) {
        _lastStage = @"native-display-layer";
        CFArrayRef attachments = CMSampleBufferGetSampleAttachmentsArray(sample, YES);
        CFMutableDictionaryRef entry = (CFMutableDictionaryRef)CFArrayGetValueAtIndex(attachments, 0);
        CFDictionarySetValue(entry, kCMSampleAttachmentKey_DisplayImmediately, kCFBooleanTrue);
        CFDictionarySetValue(entry, kCMSampleAttachmentKey_NotSync, idr ? kCFBooleanFalse : kCFBooleanTrue);
        dispatch_sync(dispatch_get_main_queue(), ^{
            if (self.video.status == AVQueuedSampleBufferRenderingStatusFailed) {
                self->_lastError = (OSStatus)self.video.error.code; self->_errors++;
                [self.video flush];
                self->_needsIDR = YES;
            }
            if ((!self->_needsIDR || idr) && self.video.readyForMoreMediaData) {
                [self.video enqueueSampleBuffer:sample]; self->_queued++;
                self->_needsIDR = NO;
            } else {
                // Dropping a dependent frame requires a new keyframe to recover.
                self->_needsIDR = YES; self->_dropped++;
                [self.video flush];
            }
            self->_renderStatus = self.video.status;
            self.label.hidden = !self.showStats;
            self.label.text = [NSString stringWithFormat:@"USB · %u×%u · native H.264\n%u frames · %u errors", self->_width, self->_height, self->_queued, self->_errors];
        });
    }
    if (result) { _lastError = result; _errors++; _needsIDR = YES; }
    if (sample) CFRelease(sample); if (block) CFRelease(block);
    [self status:@"streaming" force:NO];
}
- (void)listen {
    int listener = socket(AF_INET, SOCK_STREAM, 0); int one = 1;
    setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in addr = {0}; addr.sin_len = sizeof(addr); addr.sin_family = AF_INET;
    addr.sin_port = htons(27184); addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    _started = NSDate.date.timeIntervalSince1970;
    if (bind(listener, (struct sockaddr *)&addr, sizeof(addr)) || listen(listener, 1)) {
        [self status:@"listener-failed" force:YES]; close(listener); return;
    }
    [self status:@"listening" force:YES];
    for (;;) { @autoreleasepool {
        int fd = accept(listener, NULL, NULL); if (fd < 0) continue;
        struct timeval timeout = {10, 0};
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));
        NSString *token = [[NSString stringWithContentsOfFile:TokenPath encoding:NSUTF8StringEncoding error:nil] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        uint8_t hello[72];
        if (token.length != 64 || !ReadAll(fd, hello, sizeof(hello)) || memcmp(hello, "IPDS0001", 8) ||
            memcmp(hello + 8, token.UTF8String, 64) || !WriteAll(fd, "READY001", 8)) { close(fd); continue; }
        _received = _queued = _errors = _dropped = 0; _lastError = 0; _sps = _pps = nil;
        _started = NSDate.date.timeIntervalSince1970;
        [self resetFormat];
        while (YES) { @autoreleasepool {
            uint32_t length; if (!ReadAll(fd, &length, 4)) break; length = ntohl(length);
            if (!length || length > 8 * 1024 * 1024) break;
            NSMutableData *payload = [NSMutableData dataWithLength:length];
            if (!ReadAll(fd, payload.mutableBytes, length)) break;
            [self consume:payload];
            uint32_t ack[] = {htonl(_received), 0, htonl(_queued), htonl(_errors)};
            if (!WriteAll(fd, ack, sizeof(ack))) break;
        }}
        close(fd); [self resetFormat]; [self status:@"disconnected" force:YES];
        dispatch_sync(dispatch_get_main_queue(), ^{ [self.video flushAndRemoveImage]; self.label.hidden = NO; self.label.text = @"iPad Screen\nUSB stream stopped · Ready to reconnect"; });
    }}
}
@end

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic) UIWindow *window;
@end
@implementation AppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [ScreenController new]; [self.window makeKeyAndVisible]; return YES;
}
- (void)applicationDidBecomeActive:(UIApplication *)application { application.idleTimerDisabled = YES; }
- (void)applicationWillResignActive:(UIApplication *)application { application.idleTimerDisabled = NO; }
@end
int main(int argc, char *argv[]) { @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(AppDelegate.class)); } }
