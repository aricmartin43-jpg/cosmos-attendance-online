package in.cosmosgroups.portal;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.webkit.*;
import android.widget.*;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import android.util.Base64;
import org.json.JSONTokener;

public final class MainActivity extends Activity {
    private static final int LOCATION = 10, CAMERA = 11, SAVE = 12, PICK = 13;
    private static final int MAX_DOWNLOAD = 10 * 1024 * 1024;
    private WebView web;
    private ProgressBar progress;
    private LinearLayout error;
    private TextView errorText;
    private String geoOrigin;
    private GeolocationPermissions.Callback geoCallback;
    private PermissionRequest cameraRequest;
    private ValueCallback<Uri[]> fileCallback;
    private byte[] download;
    private boolean pageFailed;
    private final ExecutorService downloads = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(8,45,84));
        getWindow().setNavigationBarColor(Color.WHITE);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        root.setOnApplyWindowInsetsListener((v,insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });
        LinearLayout bar = new LinearLayout(this); bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Color.rgb(8,45,84)); bar.setPadding(14,4,6,4);
        TextView title = new TextView(this); title.setText("COSMOS Portal");
        title.setTextColor(Color.WHITE); title.setTextSize(16);
        bar.addView(title,new LinearLayout.LayoutParams(0,-2,1));
        Button reload = new Button(this); reload.setText("Reload"); reload.setTextSize(12);
        reload.setOnClickListener(v -> loadHome()); bar.addView(reload);
        Button browser = new Button(this); browser.setText("Browser"); browser.setTextSize(12);
        browser.setOnClickListener(v -> openExternal(OriginPolicy.HOME)); bar.addView(browser);
        root.addView(bar);
        progress = new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);
        root.addView(progress,new LinearLayout.LayoutParams(-1,5));
        FrameLayout content = new FrameLayout(this); root.addView(content,new LinearLayout.LayoutParams(-1,0,1));
        web = new WebView(this); content.addView(web,new FrameLayout.LayoutParams(-1,-1));
        error = new LinearLayout(this); error.setOrientation(LinearLayout.VERTICAL);
        error.setGravity(Gravity.CENTER); error.setPadding(30,30,30,30); error.setBackgroundColor(Color.WHITE);
        errorText = new TextView(this); errorText.setTextSize(18); errorText.setGravity(Gravity.CENTER);
        error.addView(errorText);
        Button retry = new Button(this); retry.setText("Try again");retry.setOnClickListener(v -> loadHome());error.addView(retry);
        content.addView(error,new FrameLayout.LayoutParams(-1,-1));error.setVisibility(View.GONE);
        setContentView(root);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setGeolocationEnabled(true); settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false); settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true); settings.setSupportMultipleWindows(false);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request) {
                String url=request.getUrl().toString();
                if(OriginPolicy.trusted(url))return false;
                if(request.isForMainFrame() && request.hasGesture())openExternal(url);
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request) {
                if(request.isForMainFrame() && !OriginPolicy.trusted(request.getUrl().toString()))
                    return new WebResourceResponse("text/plain","UTF-8",403,"Blocked",null,new ByteArrayInputStream(new byte[0]));
                return null;
            }
            @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap icon){pageFailed=false;progress.setVisibility(View.VISIBLE);}
            @Override public void onPageFinished(WebView view,String url){progress.setVisibility(View.GONE);CookieManager.getInstance().flush();if(!pageFailed)error.setVisibility(View.GONE);}
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError issue){if(request.isForMainFrame())showError("Cannot connect to Cosmos. Check your internet connection, then try again.");}
            @Override public void onReceivedHttpError(WebView view,WebResourceRequest request,WebResourceResponse response){if(request.isForMainFrame()&&response.getStatusCode()>=500)showError("The Cosmos server is temporarily unavailable. Please try again.");}
            @Override public void onReceivedSslError(WebView view,SslErrorHandler handler,SslError issue){handler.cancel();showError("A secure connection could not be verified. Check your phone date and time or contact your administrator.");}
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view,int value){progress.setProgress(value);}
            @Override public void onGeolocationPermissionsShowPrompt(String origin,GeolocationPermissions.Callback callback) {
                cancelLocation();
                if(!OriginPolicy.trusted(origin)||!OriginPolicy.trusted(web.getUrl())){callback.invoke(origin,false,false);return;}
                if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED){callback.invoke(origin,true,false);return;}
                geoOrigin=origin;geoCallback=callback;
                requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION},LOCATION);
            }
            @Override public void onGeolocationPermissionsHidePrompt(){cancelLocation();}
            @Override public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> {
                    if(!OriginPolicy.trusted(request.getOrigin().toString())||!OriginPolicy.trusted(web.getUrl())){request.deny();return;}
                    boolean video=false;for(String r:request.getResources())if(PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(r))video=true;
                    if(!video){request.deny();return;}
                    if(cameraRequest!=null)cameraRequest.deny();
                    if(checkSelfPermission(Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED){request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});return;}
                    cameraRequest=request;requestPermissions(new String[]{Manifest.permission.CAMERA},CAMERA);
                });
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest request){if(cameraRequest==request)cameraRequest=null;}
            @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams params) {
                if(!OriginPolicy.trusted(web.getUrl()))return false;
                if(fileCallback!=null)fileCallback.onReceiveValue(null);fileCallback=callback;
                try {startActivityForResult(params.createIntent(),PICK);}catch(ActivityNotFoundException e){fileCallback.onReceiveValue(null);fileCallback=null;toast("No file picker is available.");}
                return true;
            }
        });
        web.setDownloadListener((url,agent,disposition,mime,length) -> {
            if(!OriginPolicy.trusted(web.getUrl()))return;
            if(url.startsWith("blob:"+OriginPolicy.HOME.substring(0,OriginPolicy.HOME.length()-1)+"/")) {
                // Evaluate only a quoted blob URL on the trusted page; there is no JavaScript bridge.
                String quoted=org.json.JSONObject.quote(url);
                web.evaluateJavascript("(function(){window.__cosmosDownloadResult=null;fetch("+quoted+").then(r=>r.blob()).then(b=>{if(b.size>10485760)throw Error();let f=new FileReader();f.onload=()=>window.__cosmosDownloadResult=f.result;f.readAsDataURL(b);}).catch(()=>window.__cosmosDownloadResult='ERROR');})()",null);
                pollBlob(0,mime);
            } else if(OriginPolicy.trusted(url))downloadUrl(url,mime);
            else toast("Open this download in your browser.");
        });
        loadHome();
    }
    private void loadHome(){error.setVisibility(View.GONE);web.loadUrl(OriginPolicy.HOME);}
    private void showError(String message){pageFailed=true;progress.setVisibility(View.GONE);errorText.setText(message);error.setVisibility(View.VISIBLE);}
    private void toast(String message){Toast.makeText(this,message,Toast.LENGTH_LONG).show();}
    private void cancelLocation(){if(geoCallback!=null){geoCallback.invoke(geoOrigin,false,false);geoCallback=null;geoOrigin=null;}}
    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] results) {
        super.onRequestPermissionsResult(code,permissions,results);
        if(code==LOCATION&&geoCallback!=null){boolean fine=checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED;geoCallback.invoke(geoOrigin,fine&&OriginPolicy.trusted(web.getUrl()),false);geoCallback=null;geoOrigin=null;if(!fine)permissionHelp("Precise location is required when submitting attendance. Enable it in Android app settings, then retry.");}
        if(code==CAMERA&&cameraRequest!=null){if(checkSelfPermission(Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED&&OriginPolicy.trusted(web.getUrl()))cameraRequest.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});else cameraRequest.deny();cameraRequest=null;}
    }
    private void permissionHelp(String message){new AlertDialog.Builder(this).setMessage(message).setPositiveButton("App settings",(d,w)->startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName())))).setNegativeButton("Close",null).show();}
    private void openExternal(String url) {
        try {Uri uri=Uri.parse(url);String s=uri.getScheme();if(!("https".equals(s)||"mailto".equals(s)||"tel".equals(s))){toast("This link cannot be opened.");return;}startActivity(new Intent(Intent.ACTION_VIEW,uri).addCategory(Intent.CATEGORY_BROWSABLE));}
        catch(ActivityNotFoundException e){toast("No application can open this link.");}
    }
    private void pollBlob(int attempt,String mime){
        if(attempt>=50||!OriginPolicy.trusted(web.getUrl())){toast("Download failed. Try the browser option.");return;}
        web.evaluateJavascript("window.__cosmosDownloadResult",value->{
            try {Object parsed=new JSONTokener(value).nextValue();if(parsed instanceof String){String data=(String)parsed;if(data.equals("ERROR")){toast("Download failed or exceeds 10 MB.");return;}int comma=data.indexOf(',');if(comma>=0){byte[] bytes=Base64.decode(data.substring(comma+1),Base64.DEFAULT);web.evaluateJavascript("delete window.__cosmosDownloadResult",null);saveBytes(bytes,mime);return;}}}
            catch(Exception e){toast("Download failed.");return;}
            ui.postDelayed(()->pollBlob(attempt+1,mime),200);
        });
    }
    private void downloadUrl(String url,String mime){
        final String cookies=CookieManager.getInstance().getCookie(url);
        downloads.execute(()->{
            HttpURLConnection connection=null;
            try {
                connection=(HttpURLConnection)new URL(url).openConnection();connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(20000);connection.setReadTimeout(20000);if(cookies!=null)connection.setRequestProperty("Cookie",cookies);
                if(connection.getResponseCode()!=200)throw new IOException();
                ByteArrayOutputStream bytes=new ByteArrayOutputStream();
                try(InputStream input=connection.getInputStream()){byte[] buffer=new byte[8192];int n;while((n=input.read(buffer))!=-1){if(bytes.size()+n>MAX_DOWNLOAD)throw new IOException();bytes.write(buffer,0,n);}}
                byte[] result=bytes.toByteArray();ui.post(()->saveBytes(result,mime));
            }catch(Exception e){ui.post(()->toast("Download failed. Try opening the portal in your browser."));}finally{if(connection!=null)connection.disconnect();}
        });
    }
    private void saveBytes(byte[] bytes,String mime){
        if(bytes.length>MAX_DOWNLOAD){toast("This file exceeds the 10 MB download limit.");return;}
        if(download!=null){toast("Finish saving the current file first.");return;}
        download=bytes;Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(mime==null||mime.isEmpty()?"application/octet-stream":mime);
        intent.putExtra(Intent.EXTRA_TITLE,"cosmos-export"+(mime!=null&&mime.contains("csv")?".csv":""));
        try{startActivityForResult(intent,SAVE);}catch(ActivityNotFoundException e){download=null;toast("No document picker is available.");}
    }
    @Override protected void onActivityResult(int code,int result,Intent data){
        super.onActivityResult(code,result,data);
        if(code==PICK&&fileCallback!=null){fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result,data));fileCallback=null;}
        if(code==SAVE&&download!=null){byte[] bytes=download;download=null;if(result==RESULT_OK&&data!=null&&data.getData()!=null){try(OutputStream out=getContentResolver().openOutputStream(data.getData())){if(out==null)throw new IOException();out.write(bytes);toast("File saved.");}catch(IOException e){toast("Unable to save the file.");}}}
    }
    @Override public void onBackPressed(){if(error.getVisibility()!=View.VISIBLE&&web.canGoBack())web.goBack();else new AlertDialog.Builder(this).setMessage("Close Cosmos Employee Portal?").setPositiveButton("Close",(d,w)->finish()).setNegativeButton("Stay",null).show();}
    @Override protected void onPause(){web.onPause();CookieManager.getInstance().flush();super.onPause();}
    @Override protected void onResume(){super.onResume();if(web!=null)web.onResume();}
    @Override protected void onDestroy(){cancelLocation();if(cameraRequest!=null)cameraRequest.deny();if(fileCallback!=null)fileCallback.onReceiveValue(null);ui.removeCallbacksAndMessages(null);downloads.shutdownNow();web.destroy();super.onDestroy();}
}
